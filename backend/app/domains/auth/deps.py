from datetime import datetime, timezone
from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.domains.auth.models import AuthSession
from app.domains.users.models import User


def get_current_user(
    db: Annotated[Session, Depends(get_db)],
    portal_session: Annotated[str | None, Cookie(alias=settings.session_cookie_name)] = None,
) -> User:
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
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
DB = Annotated[Session, Depends(get_db)]


def require_admin(user: CurrentUser) -> User:
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin access required")
    return user


AdminUser = Annotated[User, Depends(require_admin)]
