from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import delete, func, select, update

from app.domains.auth.deps import DB, CurrentUser
from app.domains.notifications import push
from app.domains.notifications.models import Notification, PushSubscription
from app.domains.notifications.schemas import (
    MarkReadIn,
    NotificationOut,
    PushDeviceOut,
    PushEndpointIn,
    PushSubscribeIn,
)

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


# --- push notifications to phones / computers ----------------------------


def _device_name(ua: str) -> str:
    """'Chrome on Android' — enough to tell your devices apart in the list."""
    u = ua.lower()
    os_ = next((name for key, name in (
        ("iphone", "iPhone"), ("ipad", "iPad"), ("android", "Android"), ("windows", "Windows"),
        ("mac os", "Mac"), ("cros", "ChromeOS"), ("linux", "Linux"),
    ) if key in u), "device")
    browser = next((name for key, name in (
        ("edg/", "Edge"), ("opr/", "Opera"), ("samsungbrowser", "Samsung Internet"),
        ("firefox", "Firefox"), ("chrome", "Chrome"), ("safari", "Safari"),
    ) if key in u), "Browser")
    return f"{browser} on {os_}"


@router.get("/push/key")
def push_key(db: DB, user: CurrentUser) -> dict[str, str]:
    """The public key a browser needs to subscribe (applicationServerKey)."""
    return {"public_key": push.get_keys(db).public_key}


@router.post("/push/subscribe")
def push_subscribe(payload: PushSubscribeIn, request: Request, db: DB, user: CurrentUser) -> dict[str, bool]:
    if not push.endpoint_allowed(payload.endpoint):
        raise HTTPException(400, "That is not a recognised push service.")
    sub = db.scalar(select(PushSubscription).where(PushSubscription.endpoint == payload.endpoint))
    if sub is None:
        sub = PushSubscription(endpoint=payload.endpoint)
        db.add(sub)
    # a shared computer: the device now belongs to whoever subscribed last
    sub.user_id = user.id
    sub.p256dh = payload.keys.p256dh
    sub.auth = payload.keys.auth
    sub.origin = push.own_origin()
    sub.device = _device_name(request.headers.get("user-agent", ""))[:120]
    db.commit()
    return {"ok": True}


@router.post("/push/unsubscribe")
def push_unsubscribe(payload: PushEndpointIn, db: DB, user: CurrentUser) -> dict[str, bool]:
    db.execute(delete(PushSubscription).where(
        PushSubscription.endpoint == payload.endpoint, PushSubscription.user_id == user.id
    ))
    db.commit()
    return {"ok": True}


@router.get("/push/devices")
def push_devices(db: DB, user: CurrentUser) -> list[PushDeviceOut]:
    rows = db.scalars(
        select(PushSubscription)
        .where(PushSubscription.user_id == user.id, PushSubscription.origin == push.own_origin())
        .order_by(PushSubscription.created_at.desc())
    )
    return [PushDeviceOut.model_validate(r) for r in rows]


@router.delete("/push/devices/{device_id}")
def push_device_remove(device_id: int, db: DB, user: CurrentUser) -> dict[str, bool]:
    db.execute(delete(PushSubscription).where(
        PushSubscription.id == device_id, PushSubscription.user_id == user.id
    ))
    db.commit()
    return {"ok": True}

