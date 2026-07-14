from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.core.security import hash_password
from app.domains.auth.deps import DB, AdminUser, CurrentUser
from app.domains.hierarchy.service import assert_no_cycle, subtree_ids
from app.domains.users.models import NON_STAFF_ROLES, Role, User, UserRole
from app.domains.users.schemas import UserAdminOut, UserBrief, UserCreate, UserUpdate

router = APIRouter(prefix="/users", tags=["users"])


def _load_roles(db: DB, slugs: list[str]) -> list[Role]:
    roles = list(db.scalars(select(Role).where(Role.slug.in_(slugs))))
    if len(roles) != len(set(slugs)):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown role")
    return roles


def _set_roles(db: DB, user: User, roles: list[Role]) -> None:
    for link in db.scalars(select(UserRole).where(UserRole.user_id == user.id)):
        db.delete(link)
    db.flush()
    for role in roles:
        db.add(UserRole(user_id=user.id, role_id=role.id))


@router.get("/assignable")
def assignable_users(db: DB, user: CurrentUser) -> list[UserBrief]:
    """Everyone the current user may assign tasks to (their strict subtree;
    admin sees all active users)."""
    if user.is_admin:
        query = select(User).where(User.is_active, User.id != user.id)
    else:
        ids = subtree_ids(db, user.id)
        if not ids:
            return []
        query = select(User).where(User.id.in_(ids), User.is_active)
    return [UserBrief.model_validate(u) for u in db.scalars(query.order_by(User.full_name))]


@router.get("/staff")
def staff_users(db: DB, user: CurrentUser) -> list[UserBrief]:
    """Valid request recipients: active staff users the current user cannot
    task directly (outside their subtree, not themselves)."""
    excluded = subtree_ids(db, user.id, include_self=True)
    staff_role_ids = select(Role.id).where(Role.slug.not_in([r.value for r in NON_STAFF_ROLES]))
    query = (
        select(User)
        .join(UserRole, UserRole.user_id == User.id)
        .where(
            UserRole.role_id.in_(staff_role_ids),
            User.is_active,
            User.id.not_in(excluded),
        )
        .distinct()
        .order_by(User.full_name)
    )
    return [UserBrief.model_validate(u) for u in db.scalars(query)]


@router.get("")
def list_users(db: DB, _: AdminUser) -> list[UserAdminOut]:
    users = db.scalars(select(User).order_by(User.full_name))
    return [UserAdminOut.model_validate(u) for u in users]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_user(payload: UserCreate, db: DB, _: AdminUser) -> UserAdminOut:
    email = payload.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")
    if payload.manager_id is not None and db.get(User, payload.manager_id) is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Manager not found")

    user = User(
        email=email,
        full_name=payload.full_name,
        hashed_password=hash_password(payload.password),
        department=payload.department,
        manager_id=payload.manager_id,
    )
    db.add(user)
    db.flush()
    _set_roles(db, user, _load_roles(db, payload.roles))
    db.commit()
    db.refresh(user)
    return UserAdminOut.model_validate(user)


@router.patch("/{user_id}")
def update_user(user_id: int, payload: UserUpdate, db: DB, admin: AdminUser) -> UserAdminOut:
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
        user.manager_id = None
    elif payload.manager_id is not None:
        if db.get(User, payload.manager_id) is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Manager not found")
        if not assert_no_cycle(db, user.id, payload.manager_id):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Invalid manager: would create a cycle in the hierarchy",
            )
        user.manager_id = payload.manager_id

    if payload.is_active is not None:
        if user.id == admin.id and payload.is_active is False:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cannot deactivate yourself")
        user.is_active = payload.is_active

    if payload.roles is not None:
        _set_roles(db, user, _load_roles(db, payload.roles))

    db.commit()
    db.refresh(user)
    return UserAdminOut.model_validate(user)
