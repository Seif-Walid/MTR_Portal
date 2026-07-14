from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import or_, select

from app.domains.auth.deps import DB, CurrentUser
from app.domains.hierarchy.service import can_assign_task, can_send_request
from app.domains.notifications.models import NotificationType
from app.domains.notifications.service import notify
from app.domains.requests.models import RequestStatus, WorkRequest
from app.domains.requests.schemas import (
    RequestAccept,
    RequestCreate,
    RequestDecline,
    RequestOut,
)
from app.domains.tasks.models import Task
from app.domains.users.models import User

router = APIRouter(prefix="/requests", tags=["requests"])


def _to_out(db: DB, req: WorkRequest) -> RequestOut:
    out = RequestOut.model_validate(req)
    if req.created_task_id is not None:
        task = db.get(Task, req.created_task_id)
        if task is not None:
            out.created_task_status = task.status
    return out


def _get_visible(db: DB, user: User, request_id: int) -> WorkRequest:
    req = db.get(WorkRequest, request_id)
    if req is None or (
        user.id not in (req.requester_id, req.recipient_id) and not user.is_admin
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Request not found")
    return req


@router.get("")
def list_requests(db: DB, user: CurrentUser, box: str = "all") -> list[RequestOut]:
    query = select(WorkRequest)
    if box == "sent":
        query = query.where(WorkRequest.requester_id == user.id)
    elif box == "received":
        query = query.where(WorkRequest.recipient_id == user.id)
    else:
        query = query.where(
            or_(WorkRequest.requester_id == user.id, WorkRequest.recipient_id == user.id)
        )
    rows = db.scalars(query.order_by(WorkRequest.created_at.desc())).unique()
    return [_to_out(db, r) for r in rows]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_request(payload: RequestCreate, db: DB, user: CurrentUser) -> RequestOut:
    recipient = db.get(User, payload.recipient_id)
    if recipient is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Recipient not found")
    if not can_send_request(db, user, recipient):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Requests go to staff members outside your own subtree — "
            "assign a task directly to people below you",
        )
    req = WorkRequest(
        requester_id=user.id,
        recipient_id=recipient.id,
        title=payload.title,
        description=payload.description,
        priority=payload.priority,
        due_date=payload.due_date,
    )
    db.add(req)
    db.flush()
    notify(
        db,
        recipient.id,
        NotificationType.REQUEST_RECEIVED,
        f"{user.full_name} sent you a request: '{req.title}'",
        request_id=req.id,
    )
    db.commit()
    db.refresh(req)
    return _to_out(db, req)


@router.get("/{request_id}")
def get_request(request_id: int, db: DB, user: CurrentUser) -> RequestOut:
    return _to_out(db, _get_visible(db, user, request_id))


@router.post("/{request_id}/accept")
def accept_request(
    request_id: int, payload: RequestAccept, db: DB, user: CurrentUser
) -> RequestOut:
    req = _get_visible(db, user, request_id)
    if req.recipient_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the recipient can accept")
    if req.status != RequestStatus.PENDING:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Request already resolved")

    assignee_id = payload.assignee_id or user.id
    if assignee_id != user.id:
        assignee = db.get(User, assignee_id)
        if assignee is None or not can_assign_task(db, user, assignee):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "You can only delegate into your own subtree",
            )

    task = Task(
        title=req.title,
        description=req.description,
        assigner_id=user.id,
        assignee_id=assignee_id,
        due_date=req.due_date,
        priority=req.priority,
        category="request",
        origin_request_id=req.id,
    )
    db.add(task)
    db.flush()

    req.status = RequestStatus.ACCEPTED
    req.created_task_id = task.id
    req.resolved_at = datetime.now(timezone.utc)

    notify(
        db,
        req.requester_id,
        NotificationType.REQUEST_ACCEPTED,
        f"{user.full_name} accepted your request '{req.title}'",
        task_id=task.id,
        request_id=req.id,
    )
    if assignee_id != user.id:
        notify(
            db,
            assignee_id,
            NotificationType.TASK_ASSIGNED,
            f"{user.full_name} assigned you a task: '{task.title}' (from a request)",
            task_id=task.id,
        )
    db.commit()
    db.refresh(req)
    return _to_out(db, req)


@router.post("/{request_id}/decline")
def decline_request(
    request_id: int, payload: RequestDecline, db: DB, user: CurrentUser
) -> RequestOut:
    req = _get_visible(db, user, request_id)
    if req.recipient_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the recipient can decline")
    if req.status != RequestStatus.PENDING:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Request already resolved")

    req.status = RequestStatus.DECLINED
    req.decline_reason = payload.reason
    req.resolved_at = datetime.now(timezone.utc)
    notify(
        db,
        req.requester_id,
        NotificationType.REQUEST_DECLINED,
        f"{user.full_name} declined your request '{req.title}': {payload.reason}",
        request_id=req.id,
    )
    db.commit()
    db.refresh(req)
    return _to_out(db, req)
