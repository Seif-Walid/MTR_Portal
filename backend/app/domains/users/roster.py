"""Roster helpers shared by every place an account is born.

A member can sit on the roster before they ever sign in (no Gmail at import
time, or simply not signed up yet). When an account is created for an email the
roster already knows, the new account claims that roster row instead of
starting an empty one — so the member's MTR ID, participations and dues follow
them into their account."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domains.users.models import MemberProfile


def profile_for_new_account(db: Session, email: str) -> MemberProfile:
    """The roster row a brand-new account for `email` should own: an unlinked
    roster row carrying that email if there is one, otherwise a fresh empty one."""
    existing = db.scalar(
        select(MemberProfile).where(
            MemberProfile.user_id.is_(None),
            func.lower(MemberProfile.email) == email.lower(),
        )
    )
    return existing if existing is not None else MemberProfile(email=email.lower())


def next_mtr_id(db: Session) -> str:
    """The next free MTR ID, continuing after the current highest number."""
    highest = 0
    for (mtr_id,) in db.execute(select(MemberProfile.mtr_id).where(MemberProfile.mtr_id.is_not(None))):
        digits = "".join(ch for ch in mtr_id if ch.isdigit())
        if digits:
            highest = max(highest, int(digits))
    return format_mtr_id(highest + 1)


def format_mtr_id(number: int) -> str:
    return f"MTR-{number:03d}"
