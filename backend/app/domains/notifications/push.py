"""Web Push: every in-app notification also pops up on the person's phones and
computers where they turned notifications on (installed app or browser).

Standard Web Push (RFC 8030 + VAPID), so no Firebase project or paid
service: the browser vendor's push service (Google, Mozilla, Apple,
Microsoft) relays an encrypted message to the device.

Pushes queued on a session go out only after it commits, off the request
thread, like task emails (see service.py)."""

import base64
import json
import logging
import threading
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from urllib.parse import urlparse

from cryptography.hazmat.primitives import serialization
from sqlalchemy import event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.domains.notifications.models import Notification, PushKey, PushSubscription

log = logging.getLogger(__name__)

_PENDING_KEY = "pending_pushes"

# The server POSTs to whatever endpoint a browser hands it, so only accept the
# real push services' hosts — otherwise "subscribe" is a way to make the
# server call arbitrary URLs (SSRF).
PUSH_HOSTS = (
    "fcm.googleapis.com",              # Chrome, Edge on Android, Samsung, Opera
    "updates.push.services.mozilla.com",
    "push.services.mozilla.com",       # Firefox
    "web.push.apple.com",              # Safari macOS / iOS
    "notify.windows.com",              # Edge on Windows (*.notify.windows.com)
    "push.apple.com",
)


def endpoint_allowed(endpoint: str) -> bool:
    try:
        u = urlparse(endpoint)
    except ValueError:
        return False
    host = (u.hostname or "").lower()
    if u.scheme != "https" or not host:
        return False
    return any(host == h or host.endswith("." + h) for h in PUSH_HOSTS)


def own_origin() -> str:
    return settings.frontend_url.rstrip("/")


# --- signing key ----------------------------------------------------------

def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def get_keys(db: Session) -> PushKey:
    """The VAPID key pair, generated and stored on first use."""
    row = db.get(PushKey, 1)
    if row is not None:
        return row
    from py_vapid import Vapid02

    v = Vapid02()
    v.generate_keys()
    public = v.public_key.public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    row = PushKey(id=1, private_pem=v.private_pem().decode(), public_key=_b64url(public))
    try:
        with db.begin_nested():
            db.add(row)
        db.commit()
    except IntegrityError:  # another worker made it first
        db.rollback()
        row = db.get(PushKey, 1)
    return row


# --- what a notification looks like on the device ------------------------

def target_url(n: Notification) -> str:
    """Where tapping it goes — same as clicking it in the bell."""
    if n.task_id:
        return f"/tasks?task={n.task_id}"
    if n.request_id:
        return "/requests"
    if n.type == "application_received":
        return "/applications"
    return "/home"


TITLES = {
    "task_assigned": "New task",
    "task_status_changed": "Task update",
    "task_comment": "New comment",
    "request_received": "New request",
    "request_accepted": "Request accepted",
    "request_declined": "Request declined",
    "application_received": "New application",
}


def _task_details(task) -> str:
    """'Due Sun 30 Nov · High priority' — the facts worth a glance."""
    bits = []
    if task.due_date:
        bits.append(f"Due {task.due_date:%a %d %b}")
    pr = str(getattr(task.priority, "value", task.priority) or "").lower()
    if pr in ("high", "urgent", "critical"):
        bits.append(f"{pr.title()} priority")
    if getattr(task, "is_blocked", False):
        bits.append("Blocked")
    return " · ".join(bits)


def payload_for(db: Session, n: Notification) -> dict:
    """Title = what happened + to what; body = who/what changed, then the key
    facts. Android/desktop show the title bold and the first body line when
    collapsed, the rest when expanded."""
    kind = TITLES.get(str(n.type), "MindTech Portal")
    title, body = kind, n.message
    if n.task_id:
        from app.domains.tasks.models import Task

        task = db.get(Task, n.task_id)
        if task is not None:
            title = f"{kind} · {task.title}"[:120]
            # the message repeats the title in quotes; drop that echo
            body = n.message.replace(f": '{task.title}'", "").replace(f" '{task.title}'", "")
            details = _task_details(task)
            if details:
                body = f"{body}\n{details}"
    return {
        "title": title,
        "body": body[:400],
        "url": target_url(n),
        "tag": f"{n.type}:{n.task_id or n.request_id or ''}",
        "kind": str(n.type),
    }


def queue(db: Session, n: Notification) -> None:
    db.info.setdefault(_PENDING_KEY, []).append((n.user_id, payload_for(db, n), n))


def _with_ids(batch: list) -> list[tuple[int, dict]]:
    """Add each notification's id (known once flushed) so the device can
    mark exactly that one read."""
    from sqlalchemy import inspect

    out = []
    for uid, payload, n in batch:
        ident = inspect(n).identity
        out.append((uid, {**payload, "id": ident[0]} if ident else payload))
    return out


# --- delivery -------------------------------------------------------------

Sender = Callable[..., object]


def _default_sender(**kw):
    from pywebpush import webpush

    return webpush(**kw)


def deliver(db: Session, batch: Iterable[tuple[int, dict]], sender: Sender | None = None) -> int:
    """Send each (user_id, payload) to that person's devices on this origin.
    Devices the push service says are gone (404/410) are forgotten. Returns
    how many pushes were accepted."""
    from py_vapid import Vapid02
    from pywebpush import WebPushException

    batch = list(batch)
    if not batch:
        return 0
    send = sender or _default_sender
    keys = get_keys(db)
    vapid = Vapid02.from_pem(keys.private_pem.encode())
    claims_sub = f"mailto:{settings.mail_reply_to}" if settings.mail_reply_to else own_origin()

    user_ids = {uid for uid, _ in batch}
    subs = db.scalars(
        select(PushSubscription).where(
            PushSubscription.user_id.in_(user_ids),
            PushSubscription.origin == own_origin(),
        )
    ).all()
    by_user: dict[int, list[PushSubscription]] = {}
    for s in subs:
        by_user.setdefault(s.user_id, []).append(s)
    if not by_user:
        return 0

    unread = dict(
        db.execute(
            select(Notification.user_id, func.count())
            .where(Notification.user_id.in_(by_user), Notification.is_read.is_(False))
            .group_by(Notification.user_id)
        ).all()
    )

    sent = 0
    now = datetime.now(timezone.utc)
    for uid, payload in batch:
        for s in by_user.get(uid, []):
            if s.id is None or not endpoint_allowed(s.endpoint):
                continue
            data = json.dumps({**payload, "unread": unread.get(uid, 0)})
            try:
                send(
                    subscription_info={"endpoint": s.endpoint, "keys": {"p256dh": s.p256dh, "auth": s.auth}},
                    data=data,
                    vapid_private_key=vapid,
                    vapid_claims={"sub": claims_sub},
                    ttl=24 * 3600,
                    timeout=10,
                    headers={"Urgency": "high"},
                )
                s.last_used_at = now
                sent += 1
            except WebPushException as e:
                status = getattr(e.response, "status_code", None)
                if status in (404, 410):  # unsubscribed / expired: drop it
                    db.delete(s)
                else:
                    log.warning("push to subscription %s failed: %s", s.id, e)
            except Exception:
                log.exception("push to subscription %s failed", s.id)
    db.commit()
    return sent


def _run(batch: list[tuple[int, dict]]) -> None:
    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        deliver(db, batch)
    except Exception:
        log.exception("push delivery failed")
    finally:
        db.close()


def start_delivery(batch: list[tuple[int, dict]]) -> None:
    threading.Thread(target=_run, args=(batch,), daemon=True, name="push").start()


@event.listens_for(Session, "after_commit")
def _send_pending(session: Session) -> None:
    batch = session.info.pop(_PENDING_KEY, None)
    if batch:
        try:
            start_delivery(_with_ids(batch))
        except Exception:
            log.exception("could not start push delivery")


@event.listens_for(Session, "after_rollback")
def _drop_pending(session: Session) -> None:
    session.info.pop(_PENDING_KEY, None)
