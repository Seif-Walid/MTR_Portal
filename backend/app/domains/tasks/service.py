from fastapi import HTTPException, status as http_status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.domains.access import service as access
from app.domains.audit.service import log as audit_log
from app.domains.events.models import Event, EventCategory, EventStatus, EventTeam
from app.domains.hierarchy.service import subtree_ids, visible_user_ids
from app.domains.notifications.models import NotificationType
from app.domains.notifications.service import notify
from app.domains.requests.models import WorkRequest
from app.domains.tasks.models import Task, TaskComment, TaskStatus
from app.domains.users.models import User

# transition -> "assignee" (doing the work) or "reviewer" (assigner or above)
TRANSITIONS: dict[tuple[str, str], str] = {
    (TaskStatus.TODO, TaskStatus.IN_PROGRESS): "assignee",
    (TaskStatus.IN_PROGRESS, TaskStatus.TODO): "assignee",
    (TaskStatus.IN_PROGRESS, TaskStatus.SUBMITTED): "assignee",
    (TaskStatus.REVISION_REQUESTED, TaskStatus.IN_PROGRESS): "assignee",
    (TaskStatus.SUBMITTED, TaskStatus.APPROVED): "reviewer",
    (TaskStatus.SUBMITTED, TaskStatus.REVISION_REQUESTED): "reviewer",
}

STATUS_LABELS = {
    TaskStatus.TODO: "To Do",
    TaskStatus.IN_PROGRESS: "In Progress",
    TaskStatus.SUBMITTED: "Submitted for Review",
    TaskStatus.APPROVED: "Approved",
    TaskStatus.REVISION_REQUESTED: "Revision Requested",
}


def archived_team_ids(db: Session) -> set[int]:
    """Event teams whose tasks count as archived: soft-deleted teams, or teams
    whose event has been archived. Task archival is derived from this — there
    is no stored archived flag on a task."""
    rows = db.execute(
        select(EventTeam.id)
        .join(EventCategory, EventTeam.category_id == EventCategory.id)
        .join(Event, EventCategory.event_id == Event.id)
        .where(
            or_(
                EventTeam.deleted_at.is_not(None),
                Event.status == EventStatus.ARCHIVED,
            )
        )
    )
    return set(rows.scalars())


def my_team_ids(db: Session, user: User) -> set[int]:
    """Event-team ids the user is on (role seat or explicit membership)."""
    from app.domains.events.service import user_event_team_ids

    return user_event_team_ids(db, user.id)


def shared_team_options(db: Session, user: User, assignee_ids: list[int]) -> list[dict]:
    """Live event teams that *every* selected assignee is on — the teams a task
    to those people could belong to.

    A person is often on several teams, so the assigner picks which one the
    task is for; exactly one option means the UI can pick it for them. Computed
    from the assignees alone (not the assigner), so an admin tasking someone
    they share no team with still gets that person's teams to choose from —
    `shared_with_me` just marks the ones the assigner is on too."""
    if not assignee_ids:
        return []
    from app.domains.events.service import user_event_team_ids

    common: set[int] | None = None
    for uid in assignee_ids:
        teams = user_event_team_ids(db, uid)
        common = teams if common is None else (common & teams)
        if not common:
            return []
    assert common is not None
    common -= archived_team_ids(db)
    if not common:
        return []
    mine = my_team_ids(db, user)
    rows = db.execute(
        select(EventTeam, EventCategory.name, Event.name)
        .join(EventCategory, EventTeam.category_id == EventCategory.id)
        .join(Event, EventCategory.event_id == Event.id)
        .where(EventTeam.id.in_(common))
    )
    out = [
        {
            "team_id": team.id,
            "name": team.path_name,
            "category_name": category_name,
            "event_name": event_name,
            "shared_with_me": team.id in mine,
        }
        for team, category_name, event_name in rows
    ]
    return sorted(out, key=lambda o: (o["event_name"], o["category_name"], o["name"]))


def visible_tasks_query(db: Session, user: User, include_archived: bool = False):
    """Own tasks (assigned to or by me), everything in my subtree, tasks
    spawned by requests I sent (so requesters can track outcomes), plus
    team-visible tasks on any event team I'm a member of. Archived-event tasks
    are excluded unless include_archived is set."""
    scope = visible_user_ids(db, user)
    my_request_tasks = select(WorkRequest.created_task_id).where(
        WorkRequest.requester_id == user.id, WorkRequest.created_task_id.is_not(None)
    )
    team_ids = my_team_ids(db, user)
    conditions = [
        Task.assignee_id.in_(scope),
        Task.assigner_id == user.id,
        Task.id.in_(my_request_tasks),
    ]
    if team_ids:
        conditions.append(
            (Task.team_visible.is_(True)) & (Task.event_team_id.in_(team_ids))
        )
    query = select(Task).where(or_(*conditions))
    if not include_archived:
        archived = archived_team_ids(db)
        if archived:
            query = query.where(
                or_(
                    Task.event_team_id.is_(None),
                    Task.event_team_id.notin_(archived),
                )
            )
    return query


def can_view_task(db: Session, user: User, task: Task) -> bool:
    if access.is_top(db, user):
        return True
    if user.id in (task.assignee_id, task.assigner_id):
        return True
    if task.assignee_id in visible_user_ids(db, user):
        return True
    if task.team_visible and task.event_team_id is not None:
        if task.event_team_id in my_team_ids(db, user):
            return True
    if task.origin_request_id is not None:
        origin = db.get(WorkRequest, task.origin_request_id)
        if origin is not None and origin.requester_id == user.id:
            return True
    return False


def get_task_or_404(db: Session, user: User, task_id: int) -> Task:
    task = db.get(Task, task_id)
    if task is None or not can_view_task(db, user, task):
        # 404 for both to avoid leaking task existence outside the subtree
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, "Task not found")
    return task


class MoveRules:
    """Which TRANSITIONS one person may make: the assignee's moves are theirs
    (or a top-level person's); reviewing belongs to the assigner, anyone above
    them, or top level. Built once per request so a whole task list can say
    what each card allows without a query per task."""

    def __init__(self, db: Session, user: User):
        self.user_id = user.id
        self.top = access.is_top(db, user)
        self._below: set[int] | None = None
        self._db = db

    def permits(self, rule: str, task: Task) -> bool:
        if self.top:
            return True
        if rule == "assignee":
            return self.user_id == task.assignee_id
        if self.user_id == task.assigner_id:
            return True
        if self._below is None:
            self._below = subtree_ids(self._db, self.user_id)
        return task.assigner_id in self._below

    def allowed(self, task: Task) -> list[str]:
        return [
            str(to) for (frm, to), rule in TRANSITIONS.items()
            if frm == task.status and self.permits(rule, task)
        ]


def change_status(db: Session, user: User, task: Task, new_status: TaskStatus) -> Task:
    rule = TRANSITIONS.get((task.status, new_status))
    if rule is None:
        raise HTTPException(
            http_status.HTTP_400_BAD_REQUEST,
            f"Cannot move a task from '{task.status}' to '{new_status}'",
        )
    if not MoveRules(db, user).permits(rule, task):
        raise HTTPException(
            http_status.HTTP_403_FORBIDDEN,
            "Only the assignee can make this change" if rule == "assignee"
            else "Only the assigner or someone above them can review this task",
        )

    old_status = task.status
    task.status = new_status
    label = STATUS_LABELS[new_status]
    audit_log(
        db, user.id, "tasks", "status_changed", "task", task.id,
        {"from": old_status, "to": new_status, "by": user.full_name},
    )
    # notify the counterparty
    if user.id != task.assigner_id:
        notify(
            db,
            task.assigner_id,
            NotificationType.TASK_STATUS_CHANGED,
            f"'{task.title}' is now {label} ({user.full_name})",
            task_id=task.id,
        )
    if user.id != task.assignee_id:
        notify(
            db,
            task.assignee_id,
            NotificationType.TASK_STATUS_CHANGED,
            f"'{task.title}' is now {label} ({user.full_name})",
            task_id=task.id,
        )
    # keep the requester in the loop for request-spawned tasks
    if task.origin_request_id is not None:
        origin = db.get(WorkRequest, task.origin_request_id)
        if origin is not None and origin.requester_id not in (user.id, task.assigner_id, task.assignee_id):
            notify(
                db,
                origin.requester_id,
                NotificationType.TASK_STATUS_CHANGED,
                f"Your request '{origin.title}': task is now {label}",
                task_id=task.id,
                request_id=origin.id,
            )
    db.commit()
    db.refresh(task)
    return task


def can_toggle_blocked(db: Session, user: User, task: Task) -> bool:
    return access.is_top(db, user) or user.id in (task.assignee_id, task.assigner_id)


def set_blocked(db: Session, user: User, task: Task, is_blocked: bool, reason: str) -> Task:
    if not can_toggle_blocked(db, user, task):
        raise HTTPException(
            http_status.HTTP_403_FORBIDDEN,
            "Only the assignee or assigner can change the blocked state",
        )
    task.is_blocked = is_blocked
    task.blocked_reason = reason if is_blocked else ""
    audit_log(
        db, user.id, "tasks",
        "blocked" if is_blocked else "unblocked",
        "task", task.id,
        {"reason": task.blocked_reason, "by": user.full_name},
    )
    for recipient_id in {task.assigner_id, task.assignee_id}:
        if recipient_id != user.id:
            notify(
                db,
                recipient_id,
                NotificationType.TASK_STATUS_CHANGED,
                f"'{task.title}' is now {'blocked' if is_blocked else 'unblocked'} ({user.full_name})",
                task_id=task.id,
            )
    db.commit()
    db.refresh(task)
    return task


def add_comment(db: Session, user: User, task: Task, body: str) -> Task:
    comment = TaskComment(task_id=task.id, author_id=user.id, body=body)
    db.add(comment)
    for recipient_id in {task.assigner_id, task.assignee_id}:
        if recipient_id != user.id:
            notify(
                db,
                recipient_id,
                NotificationType.TASK_COMMENT,
                f"{user.full_name} commented on '{task.title}'",
                task_id=task.id,
            )
    db.commit()
    db.refresh(task)
    return task


def delete_task(db: Session, user: User, task: Task) -> None:
    """Removes a task for good. Gated only by the `tasks.delete` privilege
    (plus being able to see the task at all) — being the assigner is not
    enough, so a level without the privilege can never remove work.

    The audit row keeps the title/assignee so the trail survives the task.
    Does not commit."""
    from app.core.config import settings
    from app.domains.notifications.models import Notification
    from app.domains.tasks.models import AttachmentKind

    access.require_privilege(db, user, "tasks.delete")
    audit_log(
        db, user.id, "tasks", "deleted", "task", task.id,
        {
            "title": task.title,
            "assignee": task.assignee.full_name,
            "status": task.status,
            "by": user.full_name,
        },
    )
    # nothing else may keep pointing at the row (SQLite doesn't enforce the
    # notifications cascade unless foreign keys are switched on)
    db.query(Notification).filter(Notification.task_id == task.id).delete(
        synchronize_session=False
    )
    db.query(WorkRequest).filter(WorkRequest.created_task_id == task.id).update(
        {WorkRequest.created_task_id: None}, synchronize_session=False
    )
    stored = [
        a.stored_name for a in task.attachments
        if a.kind == AttachmentKind.FILE and a.stored_name
    ]
    db.delete(task)
    db.flush()
    for name in stored:
        try:
            (settings.upload_dir / name).unlink(missing_ok=True)
        except OSError:
            pass


def task_scopes(db: Session, user: User, base_query) -> list[dict]:
    """The events the person's tasks fall under, each with its live teams and
    how many of the (already filtered) visible tasks sit on each — what the
    Tasks page turns into one tab per event with team chips inside.

    An event shows up when a visible task belongs to one of its teams, or
    when the person is on one of its live teams (so a team with no work yet
    still has its tab). Archived events never appear."""
    from collections import Counter

    rows = db.execute(base_query.with_only_columns(Task.event_team_id)).scalars().all()
    per_team = Counter(tid for tid in rows if tid is not None)
    team_ids = set(per_team) | my_team_ids(db, user)
    if not team_ids:
        return []
    event_ids = set(db.scalars(
        select(EventCategory.event_id)
        .join(EventTeam, EventTeam.category_id == EventCategory.id)
        .where(EventTeam.id.in_(team_ids))
    ))
    events = db.scalars(
        select(Event)
        .where(Event.id.in_(event_ids), Event.status != EventStatus.ARCHIVED)
        .order_by(Event.start_date.desc().nulls_last(), Event.name)
    ).unique().all()
    from app.domains.events.models import tree_order

    out = []
    for ev in events:
        live = [t for c in ev.categories for t in c.teams if t.deleted_at is None]
        # a team's chip shows its sub-teams' tasks too, so its count rolls up
        rolled: Counter = Counter()
        for t in live:
            for holder in [t, *t.ancestors()]:
                rolled[holder.id] += per_team.get(t.id, 0)
        teams = []
        for t in tree_order(live):
            teams.append({
                "team_id": t.id,
                "name": t.name,
                "path_name": t.path_name,
                "parent_team_id": t.parent_team_id,
                "category_name": t.category.name,
                "depth": len(t.ancestors()),
                "task_count": rolled[t.id],
            })
        out.append({
            "event_id": ev.id,
            "name": ev.name,
            "kind_name": ev.kind.name if ev.kind is not None else None,
            "task_count": sum(per_team.get(t.id, 0) for t in live),
            "teams": teams,
        })
    return out
