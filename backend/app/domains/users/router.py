from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.security import hash_password
from app.domains.access import service as access
from app.domains.access.models import AccessLevel
from app.domains.audit.service import log as audit_log
from app.domains.auth.deps import DB, CurrentUser
from app.domains.hierarchy.service import taskable_user_ids
from app.domains.positions.models import Position, PositionOccupant
from app.domains.users.models import MemberProfile, User
from app.domains.users.schemas import (
    MemberProfileIn,
    MemberProfileOut,
    UserAdminOut,
    UserBrief,
    UserCreate,
    UserUpdate,
)

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/assignable")
def assignable_users(db: DB, user: CurrentUser) -> list[UserBrief]:
    """Everyone the current user may assign tasks to — themselves plus whoever
    they're connected to in the org (reporting line, seats below theirs, teams
    they lead); everyone active if they hold `tasks.assign_any`. Mirrors
    hierarchy.can_assign_task, which is what actually enforces it."""
    if access.has_privilege(db, user, "tasks.assign_any"):
        query = select(User).where(User.is_active)
    else:
        ids = taskable_user_ids(db, user)
        query = select(User).where(User.id.in_(ids), User.is_active)
    return [UserBrief.model_validate(u) for u in db.scalars(query.order_by(User.full_name))]


@router.get("/directory")
def directory(db: DB, user: CurrentUser) -> list[UserBrief]:
    """Active users, for people-pickers (e.g. event team members)."""
    access.require_privilege(db, user, "people.view")
    users = db.scalars(select(User).where(User.is_active).order_by(User.full_name))
    return [UserBrief.model_validate(u) for u in users]


@router.get("/staff")
def staff_users(db: DB, user: CurrentUser) -> list[UserBrief]:
    """Valid request recipients: active users who work with tasks and whom the
    current user cannot task directly (no org connection down to them)."""
    excluded = taskable_user_ids(db, user)
    eligible = access.users_with_privilege(db, "tasks.use") - excluded
    if not eligible:
        return []
    query = select(User).where(User.id.in_(eligible)).order_by(User.full_name)
    return [UserBrief.model_validate(u) for u in db.scalars(query)]


def _admin_out(db: DB, u: User, level_by_user: dict[int, AccessLevel | None],
               seats_by_user: dict[int, list[str]]) -> UserAdminOut:
    effective = level_by_user.get(u.id)
    out = UserAdminOut.model_validate(u)
    out.access_level_id = u.access_level_id
    out.effective_level = effective.name if effective else None
    out.effective_rank = effective.rank if effective else None
    out.seats = seats_by_user.get(u.id, [])
    out.profile = MemberProfileOut.model_validate(u.profile) if u.profile else None
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
    users = list(
        db.scalars(
            select(User).options(selectinload(User.profile)).order_by(User.full_name)
        )
    )
    ids = [u.id for u in users]
    levels = access.effective_levels_bulk(db, ids)
    seats = _seats_by_user(db, ids)
    return [_admin_out(db, u, levels, seats) for u in users]


def _resolve_level(db: DB, level_id: int | None) -> None:
    if level_id is not None and db.get(AccessLevel, level_id) is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown access level")


def _apply_profile(db: DB, user: User, data: MemberProfileIn) -> None:
    """Upsert the account's roster record. Only the fields the client actually
    sent are touched; empty strings clear a field. The profile row is created
    on demand so accounts that never had one (Google sign-ups, old-DB
    carryovers) can be given member details."""
    fields = data.model_dump(exclude_unset=True)
    fields = {k: (v if v != "" else None) for k, v in fields.items()}
    if not fields:
        return
    mtr_id = fields.get("mtr_id")
    if mtr_id:
        clash = db.scalar(
            select(MemberProfile).where(
                MemberProfile.mtr_id == mtr_id, MemberProfile.user_id != user.id
            )
        )
        if clash is not None:
            raise HTTPException(status.HTTP_409_CONFLICT, "MTR ID already in use")
    profile = user.profile
    if profile is None:
        profile = MemberProfile(user_id=user.id)
        user.profile = profile
        db.add(profile)
    for field, value in fields.items():
        setattr(profile, field, value)


@router.post("", status_code=status.HTTP_201_CREATED)
def create_user(payload: UserCreate, db: DB, actor: CurrentUser) -> UserAdminOut:
    access.require_privilege(db, actor, "users.manage")
    email = payload.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")
    _resolve_level(db, payload.access_level_id)

    # No manager set here — a new account has no place in the org chart until
    # someone seats them on the Organization page (which derives manager_id).
    user = User(
        email=email,
        full_name=payload.full_name,
        hashed_password=hash_password(payload.password),
        access_level_id=payload.access_level_id,
        profile=MemberProfile(),  # every account is a member — roster row starts empty
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

    if payload.profile is not None:
        _apply_profile(db, user, payload.profile)

    db.commit()
    db.refresh(user)
    return _admin_out(
        db, user, access.effective_levels_bulk(db, [user.id]), _seats_by_user(db, [user.id])
    )
