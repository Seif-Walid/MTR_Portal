"""Talking to Google Drive. The browser uploads straight to Google through a
resumable session the backend opens — a 1 GB assembly never passes through
the portal's server (which has well under 1 GB of RAM). Downloads stream
back through the portal so access stays gated by who may view the task.

Scope is drive.file: the portal sees only files it created, so connecting a
club account never exposes the rest of that Drive."""

import time
from collections.abc import Iterator
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException, status as http_status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.domains.drive.models import DriveConnection

SCOPE = "https://www.googleapis.com/auth/drive.file"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
API = "https://www.googleapis.com/drive/v3"
UPLOAD_API = "https://www.googleapis.com/upload/drive/v3/files"
FOLDER = "application/vnd.google-apps.folder"
ROOT_NAME = "MTR Portal uploads"
# The OAuth round-trip reuses the sign-in callback URL (already registered
# with Google); a state starting with this prefix routes it here instead.
STATE_PREFIX = "drive."

_token: dict[str, object] = {}  # {"for": refresh_token, "value": str, "until": float}
_folders: dict[tuple[str, str], str] = {}  # (parent_id, name) -> folder id


def connection(db: Session) -> DriveConnection | None:
    return db.scalar(select(DriveConnection).limit(1))


def require_connection(db: Session) -> DriveConnection:
    conn = connection(db)
    if conn is None:
        raise HTTPException(
            http_status.HTTP_409_CONFLICT,
            "File storage isn't connected yet — an admin connects a Google Drive in User Management.",
        )
    return conn


def auth_url(state: str) -> str:
    return f"{AUTH_URL}?" + urlencode({
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": f"openid email {SCOPE}",
        "access_type": "offline",
        "prompt": "consent",  # always hand back a refresh token
        "state": state,
    })


def finish_connect(db: Session, code: str, user_id: int) -> DriveConnection:
    """Exchanges the OAuth code and stores the connection (replacing any
    earlier one). The upload folder is created on first use."""
    res = httpx.post(TOKEN_URL, data={
        "client_id": settings.google_client_id,
        "client_secret": settings.google_client_secret,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": settings.google_redirect_uri,
    }, timeout=15)
    res.raise_for_status()
    tokens = res.json()
    if SCOPE not in tokens.get("scope", "").split() or not tokens.get("refresh_token"):
        raise ValueError("drive access not granted")
    info = httpx.get(USERINFO_URL, headers={"Authorization": f"Bearer {tokens['access_token']}"}, timeout=15)
    info.raise_for_status()
    for old in db.scalars(select(DriveConnection)):
        db.delete(old)
    conn = DriveConnection(email=info.json().get("email", ""), refresh_token=tokens["refresh_token"],
                           connected_by_id=user_id)
    db.add(conn)
    db.commit()
    _token.clear()
    _folders.clear()
    return conn


def _access_token(conn: DriveConnection) -> str:
    if _token.get("for") == conn.refresh_token and float(_token.get("until", 0)) > time.time() + 60:
        return str(_token["value"])
    res = httpx.post(TOKEN_URL, data={
        "client_id": settings.google_client_id,
        "client_secret": settings.google_client_secret,
        "refresh_token": conn.refresh_token,
        "grant_type": "refresh_token",
    }, timeout=15)
    if res.status_code != 200:
        raise HTTPException(http_status.HTTP_502_BAD_GATEWAY,
                            "Google Drive refused the stored connection — reconnect it in User Management.")
    body = res.json()
    _token.update({"for": conn.refresh_token, "value": body["access_token"],
                   "until": time.time() + int(body.get("expires_in", 3600))})
    return body["access_token"]


def _headers(conn: DriveConnection) -> dict[str, str]:
    return {"Authorization": f"Bearer {_access_token(conn)}"}


def _call(method: str, url: str, conn: DriveConnection, **kw) -> httpx.Response:
    try:
        res = httpx.request(method, url, headers={**_headers(conn), **kw.pop("headers", {})}, timeout=30, **kw)
    except httpx.HTTPError as exc:
        raise HTTPException(http_status.HTTP_502_BAD_GATEWAY, "Google Drive is unreachable") from exc
    if res.status_code >= 400:
        print(f"[drive] {method} {url} -> {res.status_code} {res.text[:300]}")
        raise HTTPException(http_status.HTTP_502_BAD_GATEWAY, "Google Drive rejected the request")
    return res


def _folder(conn: DriveConnection, parent: str, name: str) -> str:
    name = name.replace("'", "’")[:200] or "Untitled"
    key = (parent, name)
    if key in _folders:
        return _folders[key]
    q = f"name = '{name}' and mimeType = '{FOLDER}' and '{parent}' in parents and trashed = false"
    found = _call("GET", f"{API}/files", conn, params={"q": q, "fields": "files(id)"}).json()["files"]
    if found:
        _folders[key] = found[0]["id"]
    else:
        _folders[key] = _call("POST", f"{API}/files", conn, json={
            "name": name, "mimeType": FOLDER, "parents": [parent]}).json()["id"]
    return _folders[key]


def folder_path(db: Session, conn: DriveConnection, parts: list[str]) -> str:
    """Folder id for ROOT/parts…, creating what's missing."""
    if not conn.root_folder_id:
        conn.root_folder_id = _call("POST", f"{API}/files", conn, json={
            "name": ROOT_NAME, "mimeType": FOLDER}).json()["id"]
        db.commit()
    parent = conn.root_folder_id
    for part in parts:
        parent = _folder(conn, parent, part)
    return parent


def start_upload(conn: DriveConnection, *, folder_id: str, name: str, content_type: str,
                 size: int, origin: str | None, app_properties: dict[str, str]) -> str:
    """Opens a resumable upload session and returns its URL; the browser PUTs
    the file bytes there itself. Passing the browser's Origin is what lets it
    call Google cross-origin."""
    headers = {"X-Upload-Content-Type": content_type, "X-Upload-Content-Length": str(size)}
    if origin:
        headers["Origin"] = origin
    res = _call("POST", UPLOAD_API, conn, params={"uploadType": "resumable", "fields": "id"},
                headers=headers, json={"name": name, "parents": [folder_id],
                                       "appProperties": app_properties})
    return res.headers["Location"]


def file_meta(conn: DriveConnection, file_id: str) -> dict:
    return _call("GET", f"{API}/files/{file_id}", conn, params={
        "fields": "id,name,size,mimeType,appProperties,webViewLink"}).json()


def stream(conn: DriveConnection, file_id: str) -> Iterator[bytes]:
    """The file's bytes in chunks — never the whole file in memory."""
    with httpx.stream("GET", f"{API}/files/{file_id}", params={"alt": "media"},
                      headers=_headers(conn), timeout=60) as res:
        if res.status_code >= 400:
            raise HTTPException(http_status.HTTP_502_BAD_GATEWAY, "Google Drive refused the download")
        yield from res.iter_bytes(1024 * 1024)
