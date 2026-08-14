import secrets

from fastapi import APIRouter, Header, HTTPException, status

from app.core import gsheets
from app.core.config import settings
from app.domains.auth.deps import DB
from app.domains.sync import service

router = APIRouter(prefix="/sync", tags=["sync"])


@router.post("/reconcile")
def reconcile(db: DB, x_sheet_token: str = Header(default="")) -> dict:
    """Live two-way sync for every tab. Called on a timer by the spreadsheet's
    bound Apps Script (and can be pinged after a bulk edit), so the DB and the
    sheet stay mirrors of one another with no button press. Authenticated by the
    shared sheet-sync token, not a user session — same trust model as the
    per-edit webhook: whoever can reach the token can write the mirrored tables,
    so the sheet itself must stay restricted to the same people."""
    token = settings.sheets_sync_token
    if not token:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Live sheet sync is not enabled")
    if not secrets.compare_digest(x_sheet_token, token):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid sheet-sync token")
    sid = settings.google_sheets_spreadsheet_id
    if not (gsheets.credentials_available() and sid):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Google Sheets is not configured on the server.")
    results = service.reconcile_all(db, sid, None)
    ok = all(r.get("ok") for r in results.values())
    return {"ok": ok, "tabs": results}
