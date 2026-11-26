import hashlib
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.domains.access import service as access
from app.core.security import hash_password, verify_password
from app.domains.applications.models import Application, ApplicationSource, ApplicationStatus
from app.domains.applications.schemas import ApplicationIn
from app.domains.events.models import Event, EventStatus
from app.domains.members.service import digits, roster
from app.domains.notifications.models import NotificationType
from app.domains.notifications.service import notify
from app.domains.users.models import User

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


# an entry request still waiting on someone (not accepted, not declined)
OPEN_STATUSES = (ApplicationStatus.NEW, ApplicationStatus.CONTACTED, ApplicationStatus.WAITLISTED)


def _rate_limit(db: Session, sender: str | None) -> None:
    if sender is None:
        return
    recent = db.scalar(
        select(func.count(Application.id)).where(
            Application.client_hash == sender,
            Application.created_at >= _now() - timedelta(hours=1),
        )
    )
    if recent >= PER_HOUR:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many applications from this connection — try again in an hour",
        )


def open_entry_request(db: Session, email: str) -> Application | None:
    return db.scalar(
        select(Application)
        .where(
            func.lower(Application.email) == email.lower(),
            Application.source == ApplicationSource.PORTAL,
            Application.status.in_(OPEN_STATUSES),
            Application.member_id.is_(None),
        )
        .order_by(Application.created_at.desc())
        .limit(1)
    )


def pending_entry(db: Session, email: str, password: str) -> bool:
    """Is this someone signing in before their entry request was accepted?
    Only said when the password matches the one they chose, so the sign-in
    form can't be used to find out who has asked."""
    app = open_entry_request(db, email)
    return app is not None and app.password_hash is not None and verify_password(password, app.password_hash)


def check_entry_phone(payload) -> str:
    """The one Request-entry rule the schema can't express. Checked before the
    email is looked up, so the answer never depends on whether it's a member."""
    phone = (payload.phone or "").strip()
    if not 8 <= len("".join(ch for ch in phone if ch.isdigit())) <= 15:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Enter a phone number we can reach on WhatsApp")
    return phone


def request_entry(db: Session, payload, sender: str | None) -> Application | None:
    """File (or refresh) a portal "Request entry" as an application for a
    reviewer to accept or decline. Asking again while one is still open
    updates it instead of adding another — but only for whoever filed it
    (same password): anyone else typing that email changes nothing, so a
    stranger can't rewrite someone's request. Returns None when ignored."""
    phone = check_entry_phone(payload)
    now = _now()
    answers = {
        "full_name": " ".join(payload.full_name.split()),
        "email": payload.email.lower(),
        "phone": phone,
        "school": (payload.school or "").strip(),
        "year": (payload.year or "").strip(),
        "motivation": (payload.why or "").strip(),
        "password_hash": hash_password(payload.password),
    }
    app = open_entry_request(db, payload.email)
    if app is not None:
        if app.password_hash is None or not verify_password(payload.password, app.password_hash):
            return None
        for k, v in answers.items():
            setattr(app, k, v)
        app.updated_at = now
        db.commit()
        return app
    _rate_limit(db, sender)
    app = Application(**answers, source=ApplicationSource.PORTAL, client_hash=sender,
                      created_at=now, updated_at=now)
    db.add(app)
    db.flush()
    for uid in reviewer_ids(db):
        notify(db, uid, NotificationType.APPLICATION_RECEIVED,
               f"{app.full_name} requested entry to the portal")
    db.commit()
    return app


def submit(db: Session, payload: ApplicationIn, sender: str | None) -> Application | None:
    """Store a website application. Returns None for a honeypot hit, which the
    caller still answers with success so the bot learns nothing."""
    if payload.website:
        return None
    now = _now()
    _rate_limit(db, sender)

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
            Application.source == ApplicationSource.WEBSITE,
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


def roster_index(db: Session) -> tuple[dict[str, list[User]], dict[str, list[User]]]:
    """Members keyed by lower-cased email and by phone digits, built once per
    list call."""
    by_email: dict[str, list[User]] = {}
    by_phone: dict[str, list[User]] = {}
    for m in roster(db):
        if m.email:
            by_email.setdefault(m.email.lower(), []).append(m)
        if d := digits(m.phone):
            by_phone.setdefault(d, []).append(m)
    return by_email, by_phone


def roster_matches(app: Application, index) -> list[tuple[User, list[str]]]:
    by_email, by_phone = index
    found: dict[int, tuple[User, list[str]]] = {}
    for m in by_email.get(app.email.lower(), []):
        found.setdefault(m.id, (m, []))[1].append("email")
    for m in by_phone.get(digits(app.phone) or "", []):
        found.setdefault(m.id, (m, []))[1].append("phone")
    return list(found.values())
