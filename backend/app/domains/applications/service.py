import hashlib
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.domains.access import service as access
from app.domains.applications.models import Application, ApplicationStatus
from app.domains.applications.schemas import ApplicationIn
from app.domains.events.models import Event, EventStatus
from app.domains.members.service import digits, roster
from app.domains.notifications.models import NotificationType
from app.domains.notifications.service import notify
from app.domains.users.models import MemberProfile, User

# A person (well, an IP) can send this many applications an hour. Generous
# for a family or a school lab sharing one connection; useless to a spammer.
PER_HOUR = 5
# Sending the form again within a day replaces the earlier answers instead of
# adding a second application — a double click or a fixed typo.
RESUBMIT_WINDOW = timedelta(days=1)
REVIEW_PRIVILEGE = "members.edit"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def client_hash(request: Request) -> str | None:
    """Salted hash of the sender's IP. Production reaches the backend through
    Caddy (which sets X-Forwarded-For to the real client, ignoring whatever the
    client sent) and then nginx (which appends Caddy), so the first entry is
    the browser's address."""
    forwarded = request.headers.get("x-forwarded-for", "")
    ip = forwarded.split(",")[0].strip() or (request.client.host if request.client else "")
    if not ip:
        return None
    return hashlib.sha256(f"{settings.application_ip_salt}:{ip}".encode()).hexdigest()


def submit(db: Session, payload: ApplicationIn, sender: str | None) -> Application | None:
    """Store a website application. Returns None for a honeypot hit, which the
    caller still answers with success so the bot learns nothing."""
    if payload.website:
        return None
    now = _now()
    if sender is not None:
        recent = db.scalar(
            select(func.count(Application.id)).where(
                Application.client_hash == sender,
                Application.created_at >= now - timedelta(hours=1),
            )
        )
        if recent >= PER_HOUR:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "Too many applications from this connection — try again in an hour",
            )

    event = None
    if payload.event_id is not None:
        event = db.get(Event, payload.event_id)
        if event is None or event.status != EventStatus.ACTIVE or not event.applications_open:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Applications for that event are closed — refresh the page to see what's open",
            )

    answers = {
        "event_id": payload.event_id,
        "full_name": payload.name,
        "email": payload.email,
        "phone": payload.phone,
        "school": payload.school,
        "year": payload.year,
        "subteam": payload.subteam,
        "motivation": payload.why,
    }
    app = db.scalar(
        select(Application)
        .where(
            Application.email == payload.email,
            # applying to a second event is a second application, not a fix
            Application.event_id.is_(None) if payload.event_id is None
            else Application.event_id == payload.event_id,
            Application.status == ApplicationStatus.NEW,
            Application.created_at >= now - RESUBMIT_WINDOW,
        )
        .order_by(Application.created_at.desc())
        .limit(1)
    )
    if app is not None:
        for k, v in answers.items():
            setattr(app, k, v)
        app.updated_at = now
        db.commit()
        return app

    app = Application(**answers, client_hash=sender, created_at=now, updated_at=now)
    db.add(app)
    db.flush()
    for uid in reviewer_ids(db):
        notify(
            db, uid, NotificationType.APPLICATION_RECEIVED,
            f"New application from {app.full_name} ({app.year})"
            + (f" for {event.name}" if event else ""),
        )
    db.commit()
    return app


def reviewer_ids(db: Session) -> list[int]:
    """Active accounts whose level lets them act on applications."""
    ids = list(db.scalars(select(User.id).where(User.is_active.is_(True))))
    keys = access.privileges_bulk(db, ids)
    return [uid for uid in ids if REVIEW_PRIVILEGE in keys.get(uid, set())]


def roster_index(db: Session) -> tuple[dict[str, list[MemberProfile]], dict[str, list[MemberProfile]]]:
    """Roster members keyed by lower-cased email (roster or account) and by
    phone digits, built once per list call."""
    by_email: dict[str, list[MemberProfile]] = {}
    by_phone: dict[str, list[MemberProfile]] = {}
    for m in roster(db):
        emails = {(m.email or "").lower(), (m.user.email.lower() if m.user else "")} - {""}
        for e in emails:
            by_email.setdefault(e, []).append(m)
        if d := digits(m.phone):
            by_phone.setdefault(d, []).append(m)
    return by_email, by_phone


def roster_matches(app: Application, index) -> list[tuple[MemberProfile, list[str]]]:
    by_email, by_phone = index
    found: dict[int, tuple[MemberProfile, list[str]]] = {}
    for m in by_email.get(app.email.lower(), []):
        found.setdefault(m.id, (m, []))[1].append("email")
    for m in by_phone.get(digits(app.phone) or "", []):
        found.setdefault(m.id, (m, []))[1].append("phone")
    return list(found.values())
