"""Connecting the portal's file storage (a Google Drive) and its status."""

import secrets

from fastapi import APIRouter, status
from fastapi.responses import RedirectResponse

from app.core.config import settings
from app.domains.access import service as access
from app.domains.auth.deps import DB, CurrentUser
from app.domains.drive import service

router = APIRouter(prefix="/drive", tags=["drive"])

STATE_COOKIE = "g_oauth_state"  # shared with sign-in: same callback URL


@router.get("/status")
def drive_status(db: DB, user: CurrentUser) -> dict:
    conn = service.connection(db)
    return {
        "connected": conn is not None,
        "email": conn.email if conn and access.has_privilege(db, user, "users.manage") else None,
        "max_upload_mb": settings.drive_max_upload_mb,
    }


@router.get("/connect")
def connect(db: DB, user: CurrentUser) -> RedirectResponse:
    """Sends an admin to Google to grant the portal its own corner of a
    Drive (drive.file). Comes back through the sign-in callback."""
    access.require_privilege(db, user, "users.manage")
    state = service.STATE_PREFIX + secrets.token_urlsafe(24)
    response = RedirectResponse(service.auth_url(state))
    response.set_cookie(STATE_COOKIE, state, max_age=600, httponly=True, samesite="lax",
                        secure=settings.cookie_secure)
    return response


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
def disconnect(db: DB, user: CurrentUser) -> None:
    """Forgets the connection. Files already in the Drive stay there."""
    access.require_privilege(db, user, "users.manage")
    conn = service.connection(db)
    if conn is not None:
        db.delete(conn)
        db.commit()
