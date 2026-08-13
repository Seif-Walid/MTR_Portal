import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select

from app.core.config import settings
from app.domains.audit.models import AuditLog
from app.domains.audit.service import log as audit_log
from app.domains.access import service as access
from app.domains.auth.deps import DB, CurrentUser
from app.domains.events.models import EventTeam
from app.domains.events.service import team_member_user_ids
from app.domains.hierarchy.service import can_assign_task
from app.domains.notifications.models import NotificationType
from app.domains.notifications.service import notify
from app.domains.tasks.models import Task, TaskAttachment
from app.domains.tasks.schemas import (
    AttachmentOut,
    BlockedChange,
    StatusChange,
    TaskCommentCreate,
    TaskCreate,
    TaskEdit,
    TaskHistoryEntryOut,
    TaskOut,
    TeamOptionOut,
)
from app.domains.tasks.service import (
    add_comment,
    change_status,
    get_task_or_404,
    set_blocked,
    shared_team_options,
    visible_tasks_query,
)
from app.domains.users.models import User

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("")
def list_tasks(
    db: DB,
    user: CurrentUser,
    view: str = "assigned",  # assigned | created | all
    status_filter: str | None = None,
    assignee_id: int | None = None,
    event_team_id: int | None = None,
) -> list[TaskOut]:
    query = visible_tasks_query(db, user)
    if view == "assigned":
        query = query.where(Task.assignee_id == user.id)
    elif view == "created":
        query = query.where(Task.assigner_id == user.id)
    if status_filter:
        query = query.where(Task.status == status_filter)
    if assignee_id is not None:
        query = query.where(Task.assignee_id == assignee_id)
    if event_team_id is not None:
        query = query.where(Task.event_team_id == event_team_id)
    tasks = db.scalars(query.order_by(Task.updated_at.desc())).unique()
    return [TaskOut.model_validate(t) for t in tasks]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_task(payload: TaskCreate, db: DB, user: CurrentUser) -> list[TaskOut]:
    access.require_privilege(db, user, "tasks.assign")
    """Creates one task per assignee. With more than one assignee ("team
    assignment"), the resulting tasks share a batch_id so the assigner can
    track them together — each still moves through the workflow independently.

    With event_team_id and no assignee_ids, the task targets a whole event
    team: it fans out to the team's current members the assigner may task.
    With both, the named people are assigned and the team is the task's
    *context* — which team the work belongs to, since one person is often on
    several (see GET /tasks/team-options). Either way every resulting task is
    stamped with the team link + team_visible."""
    event_team_id: int | None = None
    assignee_ids = list(dict.fromkeys(payload.assignee_ids))  # de-dupe, keep order
    team: EventTeam | None = None
    if payload.event_team_id is not None:
        team = db.get(EventTeam, payload.event_team_id)
        if team is None or team.deleted_at is not None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Team not found")
        event_team_id = team.id

    if team is not None and not assignee_ids:
        assignees = []
        for uid in sorted(team_member_user_ids(db, team.id)):
            member = db.get(User, uid)
            if member is not None and can_assign_task(db, user, member):
                assignees.append(member)
        if not assignees:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "You are not connected above anyone on this team",
            )
    else:
        if not assignee_ids:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Pick at least one assignee")
        members = team_member_user_ids(db, team.id) if team is not None else set()
        assignees = []
        for assignee_id in assignee_ids:
            assignee = db.get(User, assignee_id)
            if assignee is None:
                raise HTTPException(
                    status.HTTP_404_NOT_FOUND, f"Assignee {assignee_id} not found"
                )
            if not can_assign_task(db, user, assignee):
                raise HTTPException(
                    status.HTTP_403_FORBIDDEN,
                    "You can only assign tasks to people connected below you in the "
                    "org — your reporting line, seats under yours, or a team you lead",
                )
            if team is not None and assignee.id not in members:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    f"{assignee.full_name} is not on that team — pick the team they "
                    "are actually on, or none at all",
                )
            assignees.append(assignee)

    batch_id = uuid.uuid4().hex if len(assignees) > 1 else None
    tasks: list[Task] = []
    for assignee in assignees:
        task = Task(
            title=payload.title,
            description=payload.description,
            assigner_id=user.id,
            assignee_id=assignee.id,
            due_date=payload.due_date,
            priority=payload.priority,
            category=payload.category,
            batch_id=batch_id,
            event_team_id=event_team_id,
            team_visible=payload.team_visible if event_team_id is not None else False,
        )
        db.add(task)
        db.flush()
        audit_log(
            db, user.id, "tasks", "created", "task", task.id,
            {"title": task.title, "assignee": assignee.full_name, "by": user.full_name},
        )
        notify(
            db,
            assignee.id,
            NotificationType.TASK_ASSIGNED,
            f"{user.full_name} assigned you a task: '{task.title}'",
            task_id=task.id,
        )
        tasks.append(task)
    db.commit()
    for task in tasks:
        db.refresh(task)
    return [TaskOut.model_validate(t) for t in tasks]


@router.get("/team-options")
def team_options(db: DB, user: CurrentUser, assignee_ids: str = "") -> list[TeamOptionOut]:
    """Which teams a task to these people could belong to — the live teams
    every one of them is on. One option means the caller can select it
    automatically; several means the assigner has to say which team the work is
    for. Declared before /{task_id} so the literal path wins."""
    try:
        ids = [int(part) for part in assignee_ids.split(",") if part.strip()]
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "assignee_ids must be numeric")
    return [TeamOptionOut(**row) for row in shared_team_options(db, user, ids)]


@router.get("/{task_id}")
def get_task(task_id: int, db: DB, user: CurrentUser) -> TaskOut:
    return TaskOut.model_validate(get_task_or_404(db, user, task_id))


@router.patch("/{task_id}")
def edit_task(task_id: int, payload: TaskEdit, db: DB, user: CurrentUser) -> TaskOut:
    task = get_task_or_404(db, user, task_id)
    if user.id != task.assigner_id and not access.is_top(db, user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the assigner can edit a task")
    changed: dict[str, str] = {}
    if payload.title is not None and payload.title != task.title:
        changed["title"] = task.title
        task.title = payload.title
    if payload.description is not None and payload.description != task.description:
        changed["description"] = "updated"
        task.description = payload.description
    if payload.clear_due_date:
        task.due_date = None
        changed["due_date"] = "cleared"
    elif payload.due_date is not None and payload.due_date != task.due_date:
        changed["due_date"] = str(task.due_date)
        task.due_date = payload.due_date
    if payload.priority is not None and payload.priority != task.priority:
        changed["priority"] = task.priority
        task.priority = payload.priority
    if payload.category is not None and payload.category != task.category:
        changed["category"] = task.category or ""
        task.category = payload.category
    if changed:
        audit_log(
            db, user.id, "tasks", "edited", "task", task.id,
            {"changed_fields": list(changed.keys()), "by": user.full_name},
        )
    db.commit()
    db.refresh(task)
    return TaskOut.model_validate(task)


@router.patch("/{task_id}/blocked")
def set_task_blocked(task_id: int, payload: BlockedChange, db: DB, user: CurrentUser) -> TaskOut:
    task = get_task_or_404(db, user, task_id)
    return TaskOut.model_validate(
        set_blocked(db, user, task, payload.is_blocked, payload.reason)
    )


@router.post("/{task_id}/comments", status_code=status.HTTP_201_CREATED)
def post_comment(task_id: int, payload: TaskCommentCreate, db: DB, user: CurrentUser) -> TaskOut:
    task = get_task_or_404(db, user, task_id)
    return TaskOut.model_validate(add_comment(db, user, task, payload.body))


@router.get("/{task_id}/history")
def task_history(task_id: int, db: DB, user: CurrentUser) -> list[TaskHistoryEntryOut]:
    """Visible to anyone who can see the task (not admin-only, unlike the
    general /audit endpoint) — this is scoped to a single task's own trail."""
    get_task_or_404(db, user, task_id)
    rows = db.scalars(
        select(AuditLog)
        .where(AuditLog.entity_type == "task", AuditLog.entity_id == task_id)
        .order_by(AuditLog.created_at.desc())
    )
    out = []
    for r in rows:
        actor = db.get(User, r.actor_id) if r.actor_id else None
        out.append(
            TaskHistoryEntryOut(
                actor=actor.full_name if actor else "—",
                action=r.action,
                detail=r.detail,
                created_at=r.created_at,
            )
        )
    return out


@router.get("/batch/{batch_id}")
def get_batch(batch_id: str, db: DB, user: CurrentUser) -> list[TaskOut]:
    """The sibling tasks created together in one team assignment. Limited to
    the assigner (or admin) — it surfaces every assignee's status at once,
    which is a manager's view, not a general task-visibility one."""
    tasks = list(db.scalars(select(Task).where(Task.batch_id == batch_id)))
    if not tasks:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Batch not found")
    if not access.is_top(db, user) and user.id != tasks[0].assigner_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the assigner can view the batch")
    return [TaskOut.model_validate(t) for t in tasks]


@router.patch("/{task_id}/status")
def set_status(task_id: int, payload: StatusChange, db: DB, user: CurrentUser) -> TaskOut:
    task = get_task_or_404(db, user, task_id)
    return TaskOut.model_validate(change_status(db, user, task, payload.status))


@router.post("/{task_id}/attachments", status_code=status.HTTP_201_CREATED)
def upload_attachment(task_id: int, file: UploadFile, db: DB, user: CurrentUser) -> AttachmentOut:
    task = get_task_or_404(db, user, task_id)
    if user.id not in (task.assigner_id, task.assignee_id) and not access.is_top(db, user):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Only the assigner or assignee can attach files"
        )
    data = file.file.read(settings.max_upload_mb * 1024 * 1024 + 1)
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"File exceeds {settings.max_upload_mb} MB limit",
        )
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(file.filename or "file").suffix[:20]
    stored_name = f"{uuid.uuid4().hex}{suffix}"
    (settings.upload_dir / stored_name).write_bytes(data)

    attachment = TaskAttachment(
        task_id=task.id,
        filename=file.filename or "file",
        stored_name=stored_name,
        content_type=file.content_type or "application/octet-stream",
        size=len(data),
        uploaded_by_id=user.id,
    )
    db.add(attachment)
    db.commit()
    db.refresh(attachment)
    return AttachmentOut.model_validate(attachment)


@router.get("/attachments/{attachment_id}")
def download_attachment(attachment_id: int, db: DB, user: CurrentUser) -> FileResponse:
    attachment = db.get(TaskAttachment, attachment_id)
    if attachment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Attachment not found")
    get_task_or_404(db, user, attachment.task_id)  # visibility check
    path = settings.upload_dir / attachment.stored_name
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File missing from storage")
    return FileResponse(path, filename=attachment.filename, media_type=attachment.content_type)
