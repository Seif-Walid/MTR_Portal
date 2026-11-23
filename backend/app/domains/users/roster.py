"""Roster helpers shared by every place a member is added."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import UNUSABLE_PASSWORD
from app.domains.access.models import AccessLevel
from app.domains.users.models import User, format_mtr_id, highest_mtr_number

# the ladder level a new member starts on — the same one the roster import gives
MEMBER_LEVEL = "Member"


def next_mtr_id(db: Session) -> str:
    """The next free MTR ID, continuing after the current highest number."""
    return format_mtr_id(highest_mtr_number(db) + 1)


def unclaimed_account(db: Session, email: str) -> User | None:
    """An account for `email` that its owner has never signed into (added from
    the roster by an admin). Signing up with that email claims it instead of
    being refused as a duplicate — the email is the member's, the record is
    theirs."""
    user = db.scalar(select(User).where(User.email == email.lower()))
    return user if user is not None and not user.claimed else None


def new_member(db: Session, **fields) -> User:
    """A member added by staff (roster form, accepted application): their
    account, unclaimed until they first sign in, on the Member level. Not
    added to the session."""
    level_id = db.scalar(select(AccessLevel.id).where(AccessLevel.name == MEMBER_LEVEL))
    return User(hashed_password=UNUSABLE_PASSWORD, access_level_id=level_id, **fields)
