from collections import defaultdict

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select

from app.domains.access import service as access
from app.domains.auth.deps import DB, CurrentUser
from app.domains.hierarchy.service import subtree_ids
from app.domains.tasks.models import Task
from app.domains.users.models import User
from app.domains.users.schemas import UserBrief

router = APIRouter(prefix="/team", tags=["team"])


class TreeNode(BaseModel):
    id: int
    full_name: str
    email: str
    department: str | None
    level: str | None  # effective access level name — the org's reflection
    manager_id: int | None
    is_active: bool
    can_manage: bool  # may the current user add/edit under this node
    children: list["TreeNode"] = []


TreeNode.model_rebuild()


@router.get("/tree")
def org_tree(db: DB, user: CurrentUser) -> list[TreeNode]:
    """Nested org chart. users.manage sees (and manages) the whole
    organization; everyone else sees the subtree rooted at themselves,
    view-only."""
    access.require_privilege(db, user, "people.view")
    if access.has_privilege(db, user, "users.manage"):
        users = db.scalars(select(User).order_by(User.full_name)).all()
        manageable: set[int] = {u.id for u in users}
    else:
        scope = subtree_ids(db, user.id, include_self=True)
        users = db.scalars(
            select(User).where(User.id.in_(scope)).order_by(User.full_name)
        ).all()
        manageable = set()

    present = {u.id for u in users}
    children_map: dict[int | None, list[User]] = defaultdict(list)
    for u in users:
        children_map[u.manager_id].append(u)

    levels = access.effective_levels_bulk(db, [u.id for u in users])

    def build(u: User) -> TreeNode:
        lvl = levels.get(u.id)
        return TreeNode(
            id=u.id,
            full_name=u.full_name,
            email=u.email,
            department=u.department,
            level=lvl.name if lvl else None,
            manager_id=u.manager_id,
            is_active=u.is_active,
            can_manage=u.id in manageable,
            children=[build(c) for c in children_map.get(u.id, [])],
        )

    if access.has_privilege(db, user, "users.manage"):
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
    access.require_privilege(db, user, "people.view")
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
