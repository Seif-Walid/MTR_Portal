from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.core.security import hash_password
from app.domains.access import service as access
from app.domains.access.models import AccessLevel
from app.domains.audit.service import log as audit_log
from app.domains.auth.deps import DB, CurrentUser
from app.domains.hierarchy.service import assert_no_cycle, subtree_ids
from app.domains.positions.models import Position, PositionOccupant
from app.domains.users.models import Department, User
from app.domains.users.schemas import UserAdminOut, UserBrief, UserCreate, UserUpdate

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/assignable")
def assignable_users(db: DB, user: CurrentUser) -> list[UserBrief]:
    """Everyone the current user may assign tasks to (their strict subtree;
    a top-level user sees all active users)."""
    if access.is_top(db, user):
        query = select(User).where(User.is_active, User.id != user.id)
    else:
        ids = subtree_ids(db, user.id)
        if not ids:
            return []
        query = select(User).where(User.id.in_(ids), User.is_active)
    return [UserBrief.model_validate(u) for u in db.scalars(query.order_by(User.full_name))]


@router.get("/directory")
def directory(db: DB, user: CurrentUser) -> list[UserBrief]:
    """Active users, for people-pickers (e.g. competition team members)."""
    access.require_privilege(db, user, "people.view")
    users = db.scalars(select(User).where(User.is_active).order_by(User.full_name))
    return [UserBrief.model_validate(u) for u in users]


@router.get("/staff")
def staff_users(db: DB, user: CurrentUser) -> list[UserBrief]:
    """Valid request recipients: active users who work with tasks and whom the
    current user cannot task directly (outside their subtree, not themselves)."""
    excluded = subtree_ids(db, user.id, include_self=True)
    eligible = access.users_with_privilege(db, "tasks.use") - excluded
    if not eligible:
        return []
    query = select(User).where(User.id.in_(eligible)).order_by(User.full_name)
    return [UserBrief.model_validate(u) for u in db.scalars(query)]


@router.get("/departments")
def list_departments(db: DB, user: CurrentUser) -> list[str]:
    access.require_privilege(db, user, "users.manage")
    return [d.value for d in Department]


def _admin_out(db: DB, u: User, level_by_user: dict[int, AccessLevel | None],
               seats_by_user: dict[int, list[str]]) -> UserAdminOut:
    effective = level_by_user.get(u.id)
    out = UserAdminOut.model_validate(u)
    out.access_level_id = u.access_level_id
    out.effective_level = effective.name if effective else None
    out.effective_rank = effective.rank if effective else None
    out.seats = seats_by_user.get(u.id, [])
    return out


def _seats_by_user(db: DB, user_ids: list[int]) -> dict[int, list[str]]:
    rows = db.execute(
        select(PositionOccupant.user_id, Position.title)
        .join(Position, Position.id == PositionOccupant.position_id)
        .where(PositionOccupant.user_id.in_(user_ids))
        .order_by(Position.title)
    )
    seats: dict[int, list[str]] = {}
    for uid, title in rows:
        seats.setdefault(uid, []).append(title)
    return seats


@router.get("")
def list_users(db: DB, user: CurrentUser) -> list[UserAdminOut]:
    """The management view: every account with its seats (straight from the
    org chart), computed effective level, and personal override."""
    access.require_privilege(db, user, "users.manage")
    users = list(db.scalars(select(User).order_by(User.full_name)))
    ids = [u.id for u in users]
    levels = access.effective_levels_bulk(db, ids)
    seats = _seats_by_user(db, ids)
    return [_admin_out(db, u, levels, seats) for u in users]


def _resolve_level(db: DB, level_id: int | None) -> None:
    if level_id is not None and db.get(AccessLevel, level_id) is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown access level")


@router.post("", status_code=status.HTTP_201_CREATED)
def create_user(payload: UserCreate, db: DB, actor: CurrentUser) -> UserAdminOut:
    access.require_privilege(db, actor, "users.manage")
    email = payload.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")
    if payload.manager_id is not None and db.get(User, payload.manager_id) is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Manager not found")
    _resolve_level(db, payload.access_level_id)

    user = User(
        email=email,
        full_name=payload.full_name,
        hashed_password=hash_password(payload.password),
        department=payload.department,
        manager_id=payload.manager_id,
        access_level_id=payload.access_level_id,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return _admin_out(
        db, user, access.effective_levels_bulk(db, [user.id]), _seats_by_user(db, [user.id])
    )


@router.patch("/{user_id}")
def update_user(user_id: int, payload: UserUpdate, db: DB, actor: CurrentUser) -> UserAdminOut:
    access.require_privilege(db, actor, "users.manage")
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")

    if payload.full_name is not None:
        user.full_name = payload.full_name
    if payload.password is not None:
        user.hashed_password = hash_password(payload.password)
    if payload.clear_department:
        user.department = None
    elif payload.department is not None:
        user.department = payload.department

    if payload.clear_manager:
        audit_log(db, actor.id, "users", "manager_changed", "user", user.id,
                  {"user": user.full_name, "before": user.manager_id, "after": None})
        user.manager_id = None
    elif payload.manager_id is not None:
        if db.get(User, payload.manager_id) is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Manager not found")
        if not assert_no_cycle(db, user.id, payload.manager_id):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Invalid manager: would create a cycle in the hierarchy",
            )
        if payload.manager_id != user.manager_id:
            audit_log(db, actor.id, "users", "manager_changed", "user", user.id,
                      {"user": user.full_name, "before": user.manager_id, "after": payload.manager_id})
        user.manager_id = payload.manager_id

    if payload.is_active is not None:
        if user.id == actor.id and payload.is_active is False:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cannot deactivate yourself")
        if payload.is_active is False:
            access.assert_not_last_top_override(db, user.id)
        if payload.is_active != user.is_active:
            audit_log(db, actor.id, "users", "activated" if payload.is_active else "deactivated",
                      "user", user.id, {"user": user.full_name})
        user.is_active = payload.is_active

    if payload.clear_access_level or payload.access_level_id is not None:
        new_level_id = None if payload.clear_access_level else payload.access_level_id
        _resolve_level(db, new_level_id)
        if new_level_id != user.access_level_id:
            # never orphan the ladder: someone must keep a top-level override
            if user.access_level_id is not None:
                current = db.get(AccessLevel, user.access_level_id)
                if current is not None and current.rank == access.top_rank(db):
                    new = db.get(AccessLevel, new_level_id) if new_level_id else None
                    if new is None or new.rank != current.rank:
                        access.assert_not_last_top_override(db, user.id)
            before = db.get(AccessLevel, user.access_level_id) if user.access_level_id else None
            after = db.get(AccessLevel, new_level_id) if new_level_id else None
            audit_log(db, actor.id, "users", "level_changed", "user", user.id,
                      {"user": user.full_name,
                       "before": before.name if before else None,
                       "after": after.name if after else None})
            user.access_level_id = new_level_id

    db.commit()
    db.refresh(user)
    return _admin_out(
        db, user, access.effective_levels_bulk(db, [user.id]), _seats_by_user(db, [user.id])
    )
