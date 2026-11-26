"""Emailed one-time links to choose a password.

The only way anything outside a signed-in session ever leads to a password
being set: forgot-password, Request entry for an email that already has an
account, and a reviewer accepting an entry request. Each sends a link to the
account's own inbox, so only whoever reads that inbox can pick the password —
never whoever typed the email into a form.
"""

import hashlib
import html as html_lib
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import BackgroundTasks
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.mail import send_email
from app.domains.auth.models import PasswordResetToken
from app.domains.users.models import User

RESET_TTL = timedelta(hours=1)
SETUP_TTL = timedelta(days=3)  # an accepted applicant may not look at mail for a while
RESET_COOLDOWN = timedelta(minutes=2)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)  # SQLite drops tzinfo


def _send(to: str, name: str, link: str, setup: bool, within: str) -> None:
    ask = ("You can now set up your MindTech Robotics portal account"
           if setup else "Someone asked to reset the password for your MindTech Robotics portal account")
    text = (
        f"Hi {name},\n\n"
        f"{ask}.\n"
        f"Open this link within {within} to choose a password:\n\n{link}\n\n"
        "If you weren't expecting this, ignore this email; nothing changes."
    )
    html = (
        f"<p>Hi {html_lib.escape(name)},</p>"
        f"<p>{ask}. Open this link within {within} to choose a password:</p>"
        f'<p><a href="{html_lib.escape(link)}">Choose my password</a></p>'
        "<p>If you weren't expecting this, ignore this email; nothing changes.</p>"
    )
    subject = "Set up your MindTech portal account" if setup else "Reset your MindTech portal password"
    send_email(to, subject, text, html)


def email_password_link(db: Session, user: User, background: BackgroundTasks | None, *,
                        setup: bool = False) -> None:
    """Mail `user` a one-time link to choose a password (one per cooldown
    window, so a form can't spam an inbox). Without `background` it sends
    right away. Commits the session."""
    if not user.is_active or not user.email:
        return
    now = datetime.now(timezone.utc)
    latest = db.scalar(
        select(PasswordResetToken.created_at)
        .where(PasswordResetToken.user_id == user.id)
        .order_by(PasswordResetToken.created_at.desc())
        .limit(1)
    )
    if latest is not None and now - aware(latest) < RESET_COOLDOWN:
        return
    ttl = SETUP_TTL if setup else RESET_TTL
    token = secrets.token_urlsafe(32)
    db.add(PasswordResetToken(token_hash=hash_token(token), user_id=user.id, expires_at=now + ttl))
    db.commit()
    link = f"{settings.frontend_url}/reset-password?token={token}"
    within = "3 days" if setup else "an hour"
    if background is None:
        _send(user.email, user.full_name, link, setup, within)
    else:
        background.add_task(_send, user.email, user.full_name, link, setup, within)
