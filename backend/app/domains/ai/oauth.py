"""OAuth 2.1 for outside AI agents (the MCP authorization spec).

An agent (Claude Code, Codex, Antigravity, claude.ai, ChatGPT...) is given
only the MCP URL. Its first call gets a 401 pointing at the protected-resource
metadata; from there it finds this authorization server, registers itself
(dynamic client registration, public client), and opens the person's browser
on /api/oauth/authorize. That bounces to the portal's consent page, where the
signed-in person approves; the agent swaps the code (with its PKCE verifier)
for an agent token. The token lasts until the person disconnects it in the
portal, and the agent's writes run directly (see `service.is_direct`).

Every URL the agent sees is built from `settings.frontend_url`, the portal's
public origin; nginx forwards /.well-known/oauth-* and /api/ to this app.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated
from urllib.parse import urlencode, urlsplit

from fastapi import APIRouter, Form, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.config import settings
from app.domains.ai import service
from app.domains.ai.mcp_http import PATH as MCP_PATH
from app.domains.ai.models import OAuthClient, OAuthCode
from app.domains.auth.deps import DB, CurrentUser

SCOPE = "portal"
CODE_TTL = timedelta(minutes=10)
LOOPBACK = {"localhost", "127.0.0.1", "[::1]", "::1"}

well_known = APIRouter(tags=["oauth"])
router = APIRouter(prefix="/oauth", tags=["oauth"])


def _base() -> str:
    return settings.frontend_url.rstrip("/")


def resource_metadata_url() -> str:
    return f"{_base()}/.well-known/oauth-protected-resource{MCP_PATH}"


# ------------------------------------------------------------- discovery
def _protected_resource() -> dict:
    return {"resource": f"{_base()}{MCP_PATH}", "authorization_servers": [_base()],
            "bearer_methods_supported": ["header"], "scopes_supported": [SCOPE],
            "resource_name": "MindTech Robotics portal"}


@well_known.get("/.well-known/oauth-protected-resource")
def protected_resource() -> dict:
    return _protected_resource()


@well_known.get("/.well-known/oauth-protected-resource" + MCP_PATH)
def protected_resource_mcp() -> dict:
    return _protected_resource()


@well_known.get("/.well-known/oauth-authorization-server")
def authorization_server() -> dict:
    base = _base()
    return {
        "issuer": base,
        "authorization_endpoint": f"{base}/api/oauth/authorize",
        "token_endpoint": f"{base}/api/oauth/token",
        "registration_endpoint": f"{base}/api/oauth/register",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
        "scopes_supported": [SCOPE],
        "authorization_response_iss_parameter_supported": True,
    }


# ---------------------------------------------------------- registration
def _allowed_redirect(uri: str) -> bool:
    try:
        parts = urlsplit(uri)
    except ValueError:
        return False
    if parts.fragment or not parts.scheme:
        return False
    if parts.scheme == "https":
        return bool(parts.hostname)
    if parts.scheme == "http":
        return parts.hostname in LOOPBACK
    # native apps' private-use schemes (cursor://, vscode://...)
    return parts.scheme not in {"javascript", "data", "file", "vbscript", "blob", "about"}


class Registration(BaseModel):
    redirect_uris: list[str] = Field(min_length=1, max_length=10)
    client_name: str | None = Field(default=None, max_length=100)


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(payload: Registration, db: DB) -> dict:
    bad = [u for u in payload.redirect_uris if len(u) > 2000 or not _allowed_redirect(u)]
    if bad:
        return JSONResponse({"error": "invalid_redirect_uri",
                             "error_description": f"Not an allowed redirect URI: {bad[0]}"}, status_code=400)
    client = OAuthClient(client_id="mtr_" + secrets.token_urlsafe(18),
                         name=(payload.client_name or "AI agent").strip()[:100] or "AI agent",
                         redirect_uris=json.dumps(payload.redirect_uris))
    db.add(client)
    db.commit()
    return {"client_id": client.client_id, "client_name": client.name,
            "client_id_issued_at": int(client.created_at.timestamp()),
            "redirect_uris": payload.redirect_uris, "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code"], "response_types": ["code"], "scope": SCOPE}


# ---------------------------------------------------------- authorization
def _redirect_matches(registered: list[str], uri: str) -> bool:
    if uri in registered:
        return True
    # RFC 8252: a native app's loopback redirect may use any port
    try:
        want = urlsplit(uri)
    except ValueError:
        return False
    if want.scheme != "http" or want.hostname not in LOOPBACK:
        return False
    for reg in registered:
        have = urlsplit(reg)
        if have.scheme == "http" and have.hostname == want.hostname and have.path == want.path:
            return True
    return False


def _client(db, client_id: str, redirect_uri: str) -> OAuthClient:
    client = db.get(OAuthClient, client_id)
    if client is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown agent (client_id). Ask it to connect again.")
    if not _redirect_matches(json.loads(client.redirect_uris), redirect_uri):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This agent's redirect address does not match its registration.")
    return client


def _with_params(uri: str, params: dict) -> str:
    params = {k: v for k, v in params.items() if v is not None}
    return f"{uri}{'&' if urlsplit(uri).query else '?'}{urlencode(params)}"


@router.get("/authorize")
def authorize(
    request: Request, db: DB,
    client_id: str, redirect_uri: str,
    response_type: str = "code", code_challenge: str = "", code_challenge_method: str = "",
    state: str | None = None,
) -> RedirectResponse:
    """Validates the request, then hands the person to the consent page."""
    _client(db, client_id, redirect_uri)
    if response_type != "code":
        return RedirectResponse(_with_params(redirect_uri, {"error": "unsupported_response_type", "state": state}))
    if not code_challenge or code_challenge_method != "S256":
        return RedirectResponse(_with_params(redirect_uri, {
            "error": "invalid_request", "error_description": "PKCE with S256 is required", "state": state}))
    return RedirectResponse(f"{_base()}/oauth/consent?{request.url.query}")


@router.get("/clients/{client_id}")
def client_info(client_id: str, user: CurrentUser, db: DB, redirect_uri: str = Query()) -> dict:
    client = _client(db, client_id, redirect_uri)
    return {"client_id": client.client_id, "name": client.name,
            "redirect_host": urlsplit(redirect_uri).hostname or urlsplit(redirect_uri).scheme}


class Decision(BaseModel):
    client_id: str
    redirect_uri: str
    code_challenge: str = Field(min_length=43, max_length=128)
    code_challenge_method: str = "S256"
    state: str | None = None
    approve: bool


@router.post("/decision")
def decide(payload: Decision, user: CurrentUser, db: DB) -> dict:
    """The consent page's Allow / Deny. Returns where to send the browser."""
    _client(db, payload.client_id, payload.redirect_uri)
    if not payload.approve:
        return {"redirect": _with_params(payload.redirect_uri, {"error": "access_denied", "state": payload.state})}
    if payload.code_challenge_method != "S256":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "PKCE with S256 is required")
    service.require_ai(db, user)
    code = secrets.token_urlsafe(32)
    db.add(OAuthCode(code_hash=hashlib.sha256(code.encode()).hexdigest(), client_id=payload.client_id,
                     user_id=user.id, redirect_uri=payload.redirect_uri, code_challenge=payload.code_challenge,
                     expires_at=datetime.now(timezone.utc) + CODE_TTL))
    db.commit()
    return {"redirect": _with_params(payload.redirect_uri, {"code": code, "state": payload.state, "iss": _base()})}


# ------------------------------------------------------------------ token
def _token_error(error: str, description: str, code: int = 400) -> JSONResponse:
    return JSONResponse({"error": error, "error_description": description}, status_code=code,
                        headers={"Cache-Control": "no-store"})


@router.post("/token")
def token(
    db: DB,
    grant_type: Annotated[str, Form()],
    code: Annotated[str, Form()] = "",
    redirect_uri: Annotated[str, Form()] = "",
    client_id: Annotated[str, Form()] = "",
    code_verifier: Annotated[str, Form()] = "",
) -> JSONResponse:
    if grant_type != "authorization_code":
        return _token_error("unsupported_grant_type", "Only authorization_code is supported")
    rec = db.scalar(select(OAuthCode).where(OAuthCode.code_hash == hashlib.sha256(code.encode()).hexdigest()))
    now = datetime.now(timezone.utc)
    if rec is None or rec.used_at is not None or service._aware(rec.expires_at) < now:
        return _token_error("invalid_grant", "The code is invalid, used or expired")
    if rec.client_id != client_id or rec.redirect_uri != redirect_uri:
        return _token_error("invalid_grant", "The code was issued to another agent or redirect")
    challenge = base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest()).rstrip(b"=").decode()
    if not code_verifier or not secrets.compare_digest(challenge, rec.code_challenge):
        return _token_error("invalid_grant", "PKCE verification failed")
    rec.used_at = now
    db.commit()
    user = db.get(service.User, rec.user_id)
    if user is None or not user.is_active:
        return _token_error("invalid_grant", "The account is disabled")
    client = db.get(OAuthClient, rec.client_id)
    access, _ = service.mint_token(db, user, None, label=service.AGENT_LABEL + client.name, expires=False)
    return JSONResponse({"access_token": access, "token_type": "Bearer", "scope": SCOPE},
                        headers={"Cache-Control": "no-store"})
