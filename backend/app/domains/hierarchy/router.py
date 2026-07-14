from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select

from app.domains.auth.deps import DB, CurrentUser
from app.domains.hierarchy.service import subtree_ids
from app.domains.tasks.models import Task
from app.domains.users.models import User
from app.domains.users.schemas import UserBrief

router = APIRouter(prefix="/team", tags=["team"])


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
