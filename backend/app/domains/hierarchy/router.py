from collections import defaultdict

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select

from app.domains.auth.deps import DB, CurrentUser
from app.domains.hierarchy.service import subtree_ids
from app.domains.tasks.models import Task
from app.domains.users.models import User
from app.domains.users.schemas import RoleOut, UserBrief

router = APIRouter(prefix="/team", tags=["team"])


class TreeNode(BaseModel):
    id: int
    full_name: str
    email: str
    department: str | None
    roles: list[RoleOut]
    manager_id: int | None
    is_active: bool
    can_manage: bool  # may the current user add/edit under this node
    children: list["TreeNode"] = []


TreeNode.model_rebuild()


@router.get("/tree")
def org_tree(db: DB, user: CurrentUser) -> list[TreeNode]:
    """Nested org chart. Admin sees the whole organization; everyone else sees
    the subtree rooted at themselves. `can_manage` marks nodes the current user
    may add people under or edit (admin everywhere; staff within their subtree)."""
    if user.is_admin:
        users = db.scalars(select(User).order_by(User.full_name)).all()
        manageable: set[int] = {u.id for u in users}
    elif user.is_ceo:
        # CEO manages the whole organization (the technical admin account aside)
        users = [u for u in db.scalars(select(User).order_by(User.full_name)) if not u.is_admin]
        manageable = {u.id for u in users}
    else:
        scope = subtree_ids(db, user.id, include_self=True)
        users = db.scalars(
            select(User).where(User.id.in_(scope)).order_by(User.full_name)
        ).all()
        # staff can manage their strict subtree (not themselves)
        manageable = subtree_ids(db, user.id) if user.is_staff else set()

    present = {u.id for u in users}
    children_map: dict[int | None, list[User]] = defaultdict(list)
    for u in users:
        children_map[u.manager_id].append(u)

    def build(u: User) -> TreeNode:
        return TreeNode(
            id=u.id,
            full_name=u.full_name,
            email=u.email,
            department=u.department,
            roles=[RoleOut.model_validate(r) for r in u.roles],
            manager_id=u.manager_id,
            is_active=u.is_active,
            can_manage=u.id in manageable,
            children=[build(c) for c in children_map.get(u.id, [])],
        )

    if user.is_admin or user.is_ceo:
        roots = [u for u in users if u.manager_id is None or u.manager_id not in present]
    else:
        roots = [u for u in users if u.id == user.id]
    return [build(r) for r in roots]


class TeamMemberOut(BaseModel):
    user: UserBrief
    manager_id: int | None
    is_direct_report: bool
    task_counts: dict[str, int]
    total_tasks: int


@router.get("")
def my_team(db: DB, user: CurrentUser) -> list[TeamMemberOut]:
    """Everyone in the current user's subtree with per-status task counts."""
    ids = subtree_ids(db, user.id)
    if not ids:
        return []
    members = db.scalars(
        select(User).where(User.id.in_(ids)).order_by(User.full_name)
    ).all()
    counts = db.execute(
        select(Task.assignee_id, Task.status, func.count())
        .where(Task.assignee_id.in_(ids))
        .group_by(Task.assignee_id, Task.status)
    ).all()
    by_user: dict[int, dict[str, int]] = {}
    for assignee_id, task_status, count in counts:
        by_user.setdefault(assignee_id, {})[task_status] = count

    return [
        TeamMemberOut(
            user=UserBrief.model_validate(m),
            manager_id=m.manager_id,
            is_direct_report=m.manager_id == user.id,
            task_counts=by_user.get(m.id, {}),
            total_tasks=sum(by_user.get(m.id, {}).values()),
        )
        for m in members
    ]


@router.get("/{member_id}/check")
def check_member(member_id: int, db: DB, user: CurrentUser) -> dict[str, bool]:
    """Whether member_id is inside the current user's subtree (used by the UI
    before drilling down; the tasks endpoint enforces this anyway)."""
    if member_id == user.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "That's you")
    return {"in_subtree": member_id in subtree_ids(db, user.id)}
