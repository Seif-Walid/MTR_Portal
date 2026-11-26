from datetime import datetime, timezone
from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core import borrowed, viewer
from app.core.config import settings
from app.core.database import get_db
from app.domains.auth.models import AuthSession
from app.domains.users.models import User


def _viewing_as(db: Session, user: User) -> User:
    from app.domains.access.service import privileges_for

    viewer.record(user.id, privileges_for(db, user))
    # whoever this request acts as: the automatic audit trail records them
    from app.domains.audit.auto import ACTOR

    db.info[ACTOR] = user.id
    return user


def get_current_user(
    db: Annotated[Session, Depends(get_db)],
    portal_session: Annotated[str | None, Cookie(alias=settings.session_cookie_name)] = None,
) -> User:
    run = borrowed.current()
    if run is not None:  # the AI assistant acting in-process as this person
        user = db.get(User, run.user_id)
        if user is None or not user.is_active:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account disabled")
        return _viewing_as(db, user)
    if not portal_session:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    session = db.get(AuthSession, portal_session)
    if session is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid session")
    expires = session.expires_at
    if expires.tzinfo is None:  # SQLite drops tzinfo
        expires = expires.replace(tzinfo=timezone.utc)
    if expires < datetime.now(timezone.utc):
        db.delete(session)
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired")
    user = db.get(User, session.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account disabled")
    return _viewing_as(db, user)


CurrentUser = Annotated[User, Depends(get_current_user)]
DB = Annotated[Session, Depends(get_db)]
