import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Cookie, HTTPException, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_password, new_session_token, verify_password
from app.domains.auth.deps import DB, CurrentUser
from app.domains.auth.models import AuthSession
from app.domains.auth.schemas import LoginIn, RegisterIn
from app.domains.hierarchy.service import subtree_ids
from app.domains.users.models import User
from app.domains.users.schemas import MeOut

router = APIRouter(prefix="/auth", tags=["auth"])

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
STATE_COOKIE = "g_oauth_state"


def _google_enabled() -> bool:
    return bool(settings.google_client_id and settings.google_client_secret)


def _me_payload(db: Session, user: User) -> MeOut:
    return MeOut(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        department=user.department,
        roles=user.roles,
        manager_id=user.manager_id,
        is_admin=user.is_admin,
        is_staff=user.is_staff,
        is_high_staff=user.is_high_staff,
        has_team=len(subtree_ids(db, user.id)) > 0,
        google_linked=user.google_linked,
    )


def _issue_session(db: Session, response: Response, user_id: int) -> None:
    token = new_session_token()
    db.add(
        AuthSession(
            token=token,
            user_id=user_id,
            expires_at=datetime.now(timezone.utc)
            + timedelta(hours=settings.session_ttl_hours),
        )
    )
    db.commit()
    response.set_cookie(
        settings.session_cookie_name,
        token,
        max_age=settings.session_ttl_hours * 3600,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
    )


@router.get("/config")
def auth_config() -> dict[str, bool]:
    return {"google_enabled": _google_enabled()}


@router.post("/login")
def login(payload: LoginIn, response: Response, db: DB) -> MeOut:
    user = db.scalar(select(User).where(User.email == payload.email.lower()))
    if user is None or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account is deactivated")
    _issue_session(db, response, user.id)
    return _me_payload(db, user)


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(payload: RegisterIn, response: Response, db: DB) -> MeOut:
    """Open self-signup: the account starts with no roles and no place in the
    hierarchy — the admin assigns those afterwards."""
    if db.scalar(select(User).where(User.email == payload.email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists")
    user = User(
        email=payload.email,
        full_name=payload.full_name,
        hashed_password=hash_password(payload.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    _issue_session(db, response, user.id)
    return _me_payload(db, user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response, db: DB, user: CurrentUser) -> None:
    for session in db.scalars(select(AuthSession).where(AuthSession.user_id == user.id)):
        db.delete(session)
    db.commit()
    response.delete_cookie(settings.session_cookie_name)


@router.get("/me")
def me(db: DB, user: CurrentUser) -> MeOut:
    return _me_payload(db, user)


def _login_error(reason: str) -> RedirectResponse:
    return RedirectResponse(f"{settings.frontend_url}/login?error={reason}")


def _domain_allowed(email: str, hd: str | None) -> bool:
    """Checked against the Workspace `hd` claim, or the email's own domain for
    personal accounts (Gmail has no `hd`). No configured allowlist = no
    restriction — this org's default is open personal-email accounts."""
    allowed = settings.google_allowed_domains_list
    if not allowed:
        return True
    domain = (hd or email.rsplit("@", 1)[-1]).lower()
    return domain in allowed


def _peek_session_user(db: Session, session_token: str | None) -> User | None:
    """Like get_current_user, but returns None instead of raising — used to
    detect "the browser already has a valid password-login session" so a
    Google round-trip can be treated as an explicit link action."""
    if not session_token:
        return None
    session = db.get(AuthSession, session_token)
    if session is None:
        return None
    expires = session.expires_at
    if expires.tzinfo is None:  # SQLite drops tzinfo
        expires = expires.replace(tzinfo=timezone.utc)
    if expires < datetime.now(timezone.utc):
        return None
    user = db.get(User, session.user_id)
    if user is None or not user.is_active:
        return None
    return user


@router.get("/google/login")
def google_login() -> RedirectResponse:
    """Kick off the Google OAuth flow. An unrecognized-but-verified Google
    email auto-provisions a new account (same as open self-registration) —
    it starts with no roles and no place in the hierarchy; an admin assigns
    those afterward. Narrow who can sign in at all via GOOGLE_ALLOWED_DOMAINS."""
    if not _google_enabled():
        return _login_error("google_not_configured")
    state = secrets.token_urlsafe(24)
    params = urlencode(
        {
            "client_id": settings.google_client_id,
            "redirect_uri": settings.google_redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "prompt": "select_account",
        }
    )
    response = RedirectResponse(f"{GOOGLE_AUTH_URL}?{params}")
    response.set_cookie(
        STATE_COOKIE,
        state,
        max_age=600,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
    )
    return response


@router.get("/google/callback")
def google_callback(
    db: DB,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    g_oauth_state: Annotated[str | None, Cookie(alias=STATE_COOKIE)] = None,
    portal_session: Annotated[str | None, Cookie(alias=settings.session_cookie_name)] = None,
) -> RedirectResponse:
    if not _google_enabled():
        return _login_error("google_not_configured")
    if error or not code:
        return _login_error("google_denied")
    if not state or not g_oauth_state or not secrets.compare_digest(state, g_oauth_state):
        return _login_error("google_state_mismatch")

    try:
        token_res = httpx.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": settings.google_redirect_uri,
            },
            timeout=15,
        )
        if token_res.status_code != 200:
            return _login_error("google_token_exchange_failed")
        access_token = token_res.json().get("access_token")
        info_res = httpx.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=15,
        )
        if info_res.status_code != 200:
            return _login_error("google_userinfo_failed")
        info = info_res.json()
    except httpx.HTTPError:
        return _login_error("google_unreachable")

    email = (info.get("email") or "").lower()
    if not email or not info.get("email_verified", False):
        return _login_error("google_email_unverified")
    if not _domain_allowed(email, info.get("hd")):
        return _login_error("google_domain_not_allowed")

    # If the browser already carries a valid password-login session, this
    # round-trip is an explicit "link my Google account" action (reached via
    # the account menu), not a sign-in attempt.
    linking_user = _peek_session_user(db, portal_session)
    if linking_user is not None:
        if linking_user.email != email:
            return _login_error("google_account_mismatch")
        linking_user.google_linked_at = datetime.now(timezone.utc)
        db.commit()
        response = RedirectResponse(f"{settings.frontend_url}/tasks?linked=true")
        response.delete_cookie(STATE_COOKIE)
        return response

    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        # Any verified Google identity may sign in — this is an alternate
        # entry point into the same open-signup model as POST /auth/register:
        # a brand-new account with no roles and no place in the hierarchy,
        # which an admin grants afterward. The domain allowlist above is the
        # only gate on who gets this far.
        user = User(
            email=email,
            full_name=info.get("name") or email.split("@")[0],
            hashed_password=hash_password(secrets.token_urlsafe(32)),
            google_linked_at=datetime.now(timezone.utc),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        response = RedirectResponse(f"{settings.frontend_url}/tasks")
        response.delete_cookie(STATE_COOKIE)
        _issue_session(db, response, user.id)
        return response
    if not user.is_active:
        return _login_error("account_disabled")
    if user.google_linked_at is None:
        # First-time collision with an existing password account: prove
        # ownership by signing in with the password once, then link
        # explicitly from the account menu — never silently match by email.
        return _login_error("link_required")

    response = RedirectResponse(f"{settings.frontend_url}/tasks")
    response.delete_cookie(STATE_COOKIE)
    _issue_session(db, response, user.id)
    return response
