from fastapi import HTTPException, status as http_status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.domains.hierarchy.service import can_review_task, visible_user_ids
from app.domains.notifications.models import NotificationType
from app.domains.notifications.service import notify
from app.domains.requests.models import WorkRequest
from app.domains.tasks.models import Task, TaskStatus
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


def visible_tasks_query(db: Session, user: User):
    """Own tasks (assigned to or by me), everything in my subtree, plus tasks
    spawned by requests I sent (so requesters can track outcomes)."""
    scope = visible_user_ids(db, user)
    my_request_tasks = select(WorkRequest.created_task_id).where(
        WorkRequest.requester_id == user.id, WorkRequest.created_task_id.is_not(None)
    )
    return select(Task).where(
        or_(
            Task.assignee_id.in_(scope),
            Task.assigner_id == user.id,
            Task.id.in_(my_request_tasks),
        )
    )


def can_view_task(db: Session, user: User, task: Task) -> bool:
    if user.is_admin:
        return True
    if user.id in (task.assignee_id, task.assigner_id):
        return True
    if task.assignee_id in visible_user_ids(db, user):
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


def change_status(db: Session, user: User, task: Task, new_status: TaskStatus) -> Task:
    rule = TRANSITIONS.get((task.status, new_status))
    if rule is None:
        raise HTTPException(
            http_status.HTTP_400_BAD_REQUEST,
            f"Cannot move a task from '{task.status}' to '{new_status}'",
        )
    if rule == "assignee":
        if user.id != task.assignee_id and not user.is_admin:
            raise HTTPException(
                http_status.HTTP_403_FORBIDDEN, "Only the assignee can make this change"
            )
    else:  # reviewer
        if not can_review_task(db, user, task.assigner_id):
            raise HTTPException(
                http_status.HTTP_403_FORBIDDEN,
                "Only the assigner or someone above them can review this task",
            )

    task.status = new_status
    label = STATUS_LABELS[new_status]
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
