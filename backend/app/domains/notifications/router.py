from fastapi import APIRouter
from sqlalchemy import func, select, update

from app.domains.auth.deps import DB, CurrentUser
from app.domains.notifications.models import Notification
from app.domains.notifications.schemas import MarkReadIn, NotificationOut

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("")
def list_notifications(db: DB, user: CurrentUser, limit: int = 50) -> list[NotificationOut]:
    rows = db.scalars(
        select(Notification)
        .where(Notification.user_id == user.id)
        .order_by(Notification.created_at.desc(), Notification.id.desc())
        .limit(min(limit, 200))
    )
    return [NotificationOut.model_validate(n) for n in rows]


@router.get("/unread-count")
def unread_count(db: DB, user: CurrentUser) -> dict[str, int]:
    count = db.scalar(
        select(func.count())
        .select_from(Notification)
        .where(Notification.user_id == user.id, Notification.is_read.is_(False))
    )
    return {"count": count or 0}


@router.post("/mark-read")
def mark_read(payload: MarkReadIn, db: DB, user: CurrentUser) -> dict[str, bool]:
    stmt = (
        update(Notification)
        .where(Notification.user_id == user.id, Notification.is_read.is_(False))
        .values(is_read=True)
    )
    if payload.ids is not None:
        stmt = stmt.where(Notification.id.in_(payload.ids))
    db.execute(stmt)
    db.commit()
    return {"ok": True}
