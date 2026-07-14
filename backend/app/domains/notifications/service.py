from sqlalchemy.orm import Session

from app.domains.notifications.models import Notification, NotificationType


def notify(
    db: Session,
    user_id: int,
    type_: NotificationType,
    message: str,
    task_id: int | None = None,
    request_id: int | None = None,
) -> Notification:
    """Queue an in-app notification. Caller owns the commit."""
    n = Notification(
        user_id=user_id, type=type_, message=message, task_id=task_id, request_id=request_id
    )
    db.add(n)
    return n
