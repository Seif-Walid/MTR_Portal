import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, BackgroundTasks, Cookie, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import throttle, viewer
from app.core.config import settings
from app.core.security import hash_password, new_session_token, verify_password
from app.domains.access import service as access
from app.domains.applications import service as applications
from app.domains.auth.deps import DB, CurrentUser
from app.domains.auth import links
from app.domains.auth.models import AuthSession, PasswordResetToken
from app.domains.drive import service as drive
from app.domains.auth.schemas import (
    ChangePasswordIn,
    ForgotPasswordIn,
    LoginIn,
    RequestEntryIn,
    ResetPasswordIn,
)
from app.domains.hierarchy.service import taskable_user_ids
from app.domains.positions.models import Position, PositionOccupant
from app.domains.users.models import User
from app.domains.users.schemas import MeOut, MemberProfileOut, SelfProfileIn

router = APIRouter(prefix="/auth", tags=["auth"])

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
STATE_COOKIE = "g_oauth_state"


def _google_enabled() -> bool:
    return bool(settings.google_client_id and settings.google_client_secret)


def _me_payload(db: Session, user: User) -> MeOut:
    levels = access.held_levels(db, user)
    level = levels[0] if levels else None
    privileges = access.privileges_of_levels(db, levels)
    viewer.record(user.id, privileges)  # their own email, even before a session exists
    seats = db.scalars(
        select(Position.title)
        .join(PositionOccupant, PositionOccupant.position_id == Position.id)
        .where(PositionOccupant.user_id == user.id)
        .order_by(Position.title)
    ).all()
    return MeOut(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        department=user.department,
        manager_id=user.manager_id,
        level=level,
        levels=[lvl.name for lvl in levels],
        privileges=sorted(privileges),
        # "has_team" gates the UI's New-task button: anyone they may actually
        # task, which now includes their event teams, not just direct reports
        has_team=len(taskable_user_ids(db, user) - {user.id}) > 0,
        google_linked=user.google_linked,
        created_at=user.created_at,
        seats=list(seats),
        profile=MemberProfileOut.model_validate(user),
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
        path="/",
    )


@router.get("/config")
def auth_config() -> dict[str, bool]:
    return {"google_enabled": _google_enabled()}


@router.post("/login")
def login(payload: LoginIn, request: Request, response: Response, db: DB) -> MeOut:
    email = payload.email.lower()
    sender = applications.client_hash(request)
    keys = (f"ip:{sender}" if sender else None, f"email:{email}")
    throttle.login_failures.check(*keys)
    user = db.scalar(select(User).where(User.email == email))
    if user is None and applications.pending_entry(db, payload.email, payload.password):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Your request for entry is still waiting for review — you can sign in once it's accepted",
        )
    if user is None or not verify_password(payload.password, user.hashed_password):
        throttle.login_failures.fail(*keys)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account is deactivated")
    _issue_session(db, response, user.id)
    return _me_payload(db, user)


@router.post("/request-entry", status_code=status.HTTP_202_ACCEPTED)
def request_entry(payload: RequestEntryIn, request: Request, background: BackgroundTasks, db: DB) -> dict:
    """Nobody can make an account for themselves. Anyone without an account
    files an entry request: it shows up in Applications, and only when someone
    with members.edit accepts it does the account exist (with the password
    chosen here).

    If the email already has an account — including one an admin added that
    was never set up — the form never sets a password or signs anyone in:
    whoever typed the email has not proved they own it. Instead the inbox gets
    a one-hour link to choose a password (the same link as "Forgot password").
    The answer is the same "pending" in every case, so the form can't be used
    to learn which emails are members."""
    email = payload.email.lower()
    sender = applications.client_hash(request)
    throttle.account_forms.check(f"ip:{sender}" if sender else None)
    throttle.account_forms.fail(f"ip:{sender}" if sender else None)
    applications.check_entry_phone(payload)  # before the lookup: same rule for everyone
    user = db.scalar(select(User).where(User.email == email))
    if user is not None:
        _email_password_link(db, user, background, setup=not user.claimed)
        return {"status": "pending"}
    try:
        applications.request_entry(db, payload, sender)
    except HTTPException as exc:
        # the per-connection application cap only exists on this branch;
        # answering it differently would tell members from non-members
        if exc.status_code != status.HTTP_429_TOO_MANY_REQUESTS:
            raise
    return {"status": "pending"}


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response, db: DB, user: CurrentUser) -> None:
    for session in db.scalars(select(AuthSession).where(AuthSession.user_id == user.id)):
        db.delete(session)
    db.commit()
    response.delete_cookie(
        settings.session_cookie_name,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )


@router.get("/me")
def me(db: DB, user: CurrentUser) -> MeOut:
    return _me_payload(db, user)


@router.put("/me/profile")
def update_my_profile(payload: SelfProfileIn, db: DB, user: CurrentUser) -> MeOut:
    """Self-service edit of the signed-in member's own roster fields. The
    org-assigned `mtr_id` is not in the payload, so it can never be changed
    here. Only fields the client actually sends are touched (partial update);
    sending an explicit null clears one."""
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(user, field, value)
    db.commit()
    return _me_payload(db, user)


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(payload: ChangePasswordIn, db: DB, user: CurrentUser) -> None:
    """Self-service password change from the profile page. Proving the current
    password guards against a hijacked session silently locking the owner out."""
    if not verify_password(payload.current_password, user.hashed_password):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is incorrect")
    if payload.new_password == payload.current_password:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "New password must differ from the current one"
        )
    user.hashed_password = hash_password(payload.new_password)
    db.commit()


_email_password_link = links.email_password_link
_hash_reset_token = links.hash_token
_aware = links.aware


@router.post("/forgot-password", status_code=status.HTTP_204_NO_CONTENT)
def forgot_password(payload: ForgotPasswordIn, request: Request, background: BackgroundTasks, db: DB) -> None:
    """Email a one-hour reset link. Always 204, whether or not the email has an
    account, so the endpoint can't be used to probe who's registered; the mail
    goes out in the background so response timing doesn't leak it either."""
    sender = applications.client_hash(request)
    throttle.account_forms.check(f"ip:{sender}" if sender else None)
    throttle.account_forms.fail(f"ip:{sender}" if sender else None)
    user = db.scalar(select(User).where(User.email == payload.email.lower()))
    if user is None:
        return
    _email_password_link(db, user, background, setup=not user.claimed)


@router.post("/reset-password", status_code=status.HTTP_204_NO_CONTENT)
def reset_password(payload: ResetPasswordIn, db: DB) -> None:
    """Redeem an emailed link: set the new password, burn every outstanding
    link for the account and sign out all its sessions."""
    row = db.get(PasswordResetToken, _hash_reset_token(payload.token))
    now = datetime.now(timezone.utc)
    if row is None or row.used_at is not None or _aware(row.expires_at) < now:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "This reset link is invalid or has expired"
        )
    user = db.get(User, row.user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "This reset link is invalid or has expired"
        )
    user.hashed_password = hash_password(payload.new_password)
    for other in db.scalars(
        select(PasswordResetToken).where(
            PasswordResetToken.user_id == user.id, PasswordResetToken.used_at.is_(None)
        )
    ):
        other.used_at = now
    for session in db.scalars(select(AuthSession).where(AuthSession.user_id == user.id)):
        db.delete(session)
    db.commit()


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
    """Kick off the Google OAuth flow. Only emails already in the database
    sign in — an unknown Google account is turned away (to "Request entry"),
    never created. GOOGLE_ALLOWED_DOMAINS can narrow it further."""
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


def _finish_drive_connect(db: Session, code: str, portal_session: str | None) -> RedirectResponse:
    """The second half of /api/drive/connect: an admin granted the portal a
    Drive. Shares this callback so no extra redirect URI has to be
    registered with Google."""
    user = _peek_session_user(db, portal_session)
    if user is None or not access.has_privilege(db, user, "users.manage"):
        return _login_error("drive_not_allowed")
    try:
        drive.finish_connect(db, code, user.id)
        outcome = "connected"
    except (httpx.HTTPError, ValueError) as exc:
        print(f"[drive_connect] failed: {exc!r}")
        outcome = "failed"
    response = RedirectResponse(f"{settings.frontend_url}/admin/users?drive={outcome}")
    response.delete_cookie(STATE_COOKIE, samesite="lax", secure=settings.cookie_secure)
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
    if state.startswith(drive.STATE_PREFIX):
        return _finish_drive_connect(db, code, portal_session)

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
            print(f"[google_callback] token exchange failed: {token_res.status_code} {token_res.text}")
            return _login_error("google_token_exchange_failed")
        access_token = token_res.json().get("access_token")
        info_res = httpx.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=15,
        )
        if info_res.status_code != 200:
            print(f"[google_callback] userinfo fetch failed: {info_res.status_code} {info_res.text}")
            return _login_error("google_userinfo_failed")
        info = info_res.json()
    except httpx.HTTPError as exc:
        print(f"[google_callback] unreachable: {exc!r}")
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
        response.delete_cookie(
            STATE_COOKIE,
            samesite="lax",
            secure=settings.cookie_secure,
        )
        return response

    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        # Google proves who you are, not that you belong: only people already
        # in the database sign in. Anyone else asks with "Request entry".
        return _login_error("not_a_member")
    if not user.is_active:
        return _login_error("account_disabled")
    if user.google_linked_at is None and not user.claimed:
        # A member added from the roster who never signed in: Google just
        # proved they own the email the roster holds for them — that is the
        # claim, so link and sign them in.
        user.google_linked_at = datetime.now(timezone.utc)
        db.commit()
    if user.google_linked_at is None:
        # First-time collision with an existing password account: prove
        # ownership by signing in with the password once, then link
        # explicitly from the account menu — never silently match by email.
        return _login_error("link_required")

    response = RedirectResponse(f"{settings.frontend_url}/tasks")
    response.delete_cookie(
        STATE_COOKIE,
        samesite="lax",
        secure=settings.cookie_secure,
    )
    _issue_session(db, response, user.id)
    return response
