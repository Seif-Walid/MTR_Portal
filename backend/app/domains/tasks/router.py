import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select

from app.core.config import settings
from app.domains.auth.deps import DB, CurrentUser
from app.domains.hierarchy.service import can_assign_task
from app.domains.notifications.models import NotificationType
from app.domains.notifications.service import notify
from app.domains.tasks.models import Task, TaskAttachment
from app.domains.tasks.schemas import (
    AttachmentOut,
    StatusChange,
    TaskCreate,
    TaskEdit,
    TaskOut,
)
from app.domains.tasks.service import (
    change_status,
    get_task_or_404,
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
    tasks = db.scalars(query.order_by(Task.updated_at.desc())).unique()
    return [TaskOut.model_validate(t) for t in tasks]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_task(payload: TaskCreate, db: DB, user: CurrentUser) -> TaskOut:
    assignee = db.get(User, payload.assignee_id)
    if assignee is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Assignee not found")
    if not can_assign_task(db, user, assignee):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "You can only assign tasks to people below you in the hierarchy",
        )
    task = Task(
        title=payload.title,
        description=payload.description,
        assigner_id=user.id,
        assignee_id=assignee.id,
        due_date=payload.due_date,
        priority=payload.priority,
        category=payload.category,
    )
    db.add(task)
    db.flush()
    notify(
        db,
        assignee.id,
        NotificationType.TASK_ASSIGNED,
        f"{user.full_name} assigned you a task: '{task.title}'",
        task_id=task.id,
    )
    db.commit()
    db.refresh(task)
    return TaskOut.model_validate(task)


@router.get("/{task_id}")
def get_task(task_id: int, db: DB, user: CurrentUser) -> TaskOut:
    return TaskOut.model_validate(get_task_or_404(db, user, task_id))


@router.patch("/{task_id}")
def edit_task(task_id: int, payload: TaskEdit, db: DB, user: CurrentUser) -> TaskOut:
    task = get_task_or_404(db, user, task_id)
    if user.id != task.assigner_id and not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the assigner can edit a task")
    if payload.title is not None:
        task.title = payload.title
    if payload.description is not None:
        task.description = payload.description
    if payload.clear_due_date:
        task.due_date = None
    elif payload.due_date is not None:
        task.due_date = payload.due_date
    if payload.priority is not None:
        task.priority = payload.priority
    if payload.category is not None:
        task.category = payload.category
    db.commit()
    db.refresh(task)
    return TaskOut.model_validate(task)


@router.patch("/{task_id}/status")
def set_status(task_id: int, payload: StatusChange, db: DB, user: CurrentUser) -> TaskOut:
    task = get_task_or_404(db, user, task_id)
    return TaskOut.model_validate(change_status(db, user, task, payload.status))


@router.post("/{task_id}/attachments", status_code=status.HTTP_201_CREATED)
def upload_attachment(task_id: int, file: UploadFile, db: DB, user: CurrentUser) -> AttachmentOut:
    task = get_task_or_404(db, user, task_id)
    if user.id not in (task.assigner_id, task.assignee_id) and not user.is_admin:
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
