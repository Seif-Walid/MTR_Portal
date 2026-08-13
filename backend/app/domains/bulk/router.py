import secrets

from fastapi import APIRouter, File, Header, HTTPException, Response, UploadFile, status
from sqlalchemy import func, select

from app.core.config import settings
from app.domains.access import service as access
from app.domains.auth.deps import DB, CurrentUser
from app.domains.bulk import service
from app.domains.bulk.registry import TABLES, TableSpec, ensure_all_tables_registered
from app.domains.bulk.schemas import (
    ApplyRequest,
    ApplyResult,
    SheetWebhookRequest,
    TableSummary,
)

XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

router = APIRouter(prefix="/bulk", tags=["bulk"])


def _spec_or_404(table: str) -> TableSpec:
    ensure_all_tables_registered()
    spec = TABLES.get(table)
    if spec is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown table '{table}'")
    return spec


def _writable_or_400(spec: TableSpec) -> TableSpec:
    if spec.read_only:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"'{spec.label}' is a read-only table"
        )
    return spec


@router.get("/tables")
def list_tables(db: DB, user: CurrentUser) -> list[TableSummary]:
    """Only the tables this user may edit — each table is gated by its own
    per-domain privilege (inventory.edit, users.manage, ...)."""
    ensure_all_tables_registered()
    out: list[TableSummary] = []
    for spec in TABLES.values():
        if not access.has_privilege(db, user, spec.privilege):
            continue
        count = db.scalar(select(func.count()).select_from(spec.model)) or 0
        out.append(TableSummary(key=spec.key, label=spec.label, row_count=count,
                                append_only=spec.append_only, read_only=spec.read_only))
    return out


@router.get("/sheets/status")
def sheets_status(user: CurrentUser) -> dict:
    """Is the Google Sheets round-trip available on this server? Drives the
    enabled state of the 'Open in Google Sheets' / 'Pull from Sheet' buttons."""
    return service.sheet_status()


@router.post("/sheet-webhook")
def sheet_webhook(
    payload: SheetWebhookRequest,
    db: DB,
    x_sheet_token: str = Header(default=""),
) -> dict:
    """Live sheet -> DB. Called by the spreadsheet's bound Apps Script on every
    edit; authenticated by a shared token (not a user session), so each edit in
    Google Sheets updates the database with no button press. Returns the row id
    so the script can write it back into a newly-inserted (blank-id) row."""
    token = settings.sheets_sync_token
    if not token:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Live sheet sync is not enabled")
    if not secrets.compare_digest(x_sheet_token, token):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid sheet-sync token")
    spec = TABLES.get(payload.tab)
    if spec is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown table '{payload.tab}'")
    _writable_or_400(spec)
    return service.webhook_apply(db, spec, payload.row, None)


@router.get("/{table}")
def get_table(table: str, db: DB, user: CurrentUser) -> dict:
    spec = _spec_or_404(table)
    access.require_privilege(db, user, spec.privilege)
    return service.read_table(db, spec)


@router.post("/{table}/validate")
def validate_table(table: str, payload: ApplyRequest, db: DB, user: CurrentUser) -> ApplyResult:
    spec = _writable_or_400(_spec_or_404(table))
    access.require_privilege(db, user, spec.privilege)
    _, errors, summary = service.validate(db, spec, payload.rows, payload.deletes)
    return ApplyResult(ok=not errors, errors=errors, summary=summary)


@router.post("/{table}")
def apply_table(table: str, payload: ApplyRequest, db: DB, user: CurrentUser) -> ApplyResult:
    spec = _writable_or_400(_spec_or_404(table))
    access.require_privilege(db, user, spec.privilege)
    result = service.apply(db, spec, payload.rows, payload.deletes, user.id)
    return ApplyResult(**result)


@router.get("/{table}/export.xlsx")
def export_xlsx(table: str, db: DB, user: CurrentUser) -> Response:
    """Download the whole table as a real .xlsx to edit in Excel / Google Sheets."""
    spec = _spec_or_404(table)
    access.require_privilege(db, user, spec.privilege)
    body = service.workbook_bytes(db, spec)
    return Response(
        content=body,
        media_type=XLSX_MEDIA,
        headers={"Content-Disposition": f'attachment; filename="{spec.key}.xlsx"'},
    )


@router.post("/{table}/upload")
async def upload_xlsx(
    table: str,
    db: DB,
    user: CurrentUser,
    file: UploadFile = File(...),
    apply: bool = False,
    delete_missing: bool = False,
) -> dict:
    """The edited sheet comes back here. `apply=false` returns a preview of what
    would change; `apply=true` commits it. `delete_missing` also removes rows the
    user deleted from the sheet (rows in the DB but absent from the file)."""
    spec = _writable_or_400(_spec_or_404(table))
    access.require_privilege(db, user, spec.privilege)
    content = await file.read()
    try:
        rows = service.parse_upload(content, file.filename or "", spec)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    plan = service.plan_upload(db, spec, rows, delete_missing)
    if not apply:
        return {"applied": False, **plan}
    if not plan["ok"]:
        return {"applied": False, **plan}
    deletes = plan["missing_ids"] if (delete_missing and plan["can_delete"]) else []
    result = service.apply(db, spec, rows, deletes, user.id)
    return {"applied": result["ok"], **result}


@router.post("/{table}/sheet/push")
def sheet_push(table: str, db: DB, user: CurrentUser) -> dict:
    """Push the current DB rows into a live Google Sheets tab and return a link
    to it. Editing happens in Google's UI; changes come back via /sheet/pull."""
    spec = _writable_or_400(_spec_or_404(table))
    access.require_privilege(db, user, spec.privilege)
    try:
        return service.push_to_sheet(db, spec)
    except RuntimeError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.post("/{table}/sheet/sync")
def sheet_sync(table: str, db: DB, user: CurrentUser) -> dict:
    """Force the live two-way reconcile for this one tab right now (pull the
    sheet's edits/adds/deletes into the DB, then push the DB back). Normally the
    spreadsheet's Apps Script timer does this every minute; this is the 'don't
    wait' button for an admin."""
    spec = _writable_or_400(_spec_or_404(table))
    access.require_privilege(db, user, spec.privilege)
    from app.core import gsheets
    from app.domains.sync import service as sync

    sid = settings.google_sheets_spreadsheet_id
    if not (gsheets.credentials_available() and sid):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Google Sheets isn't configured on the server.")
    return sync.reconcile_tab(db, sid, table, user.id)


@router.post("/{table}/sheet/pull")
def sheet_pull(
    table: str,
    db: DB,
    user: CurrentUser,
    apply: bool = False,
    delete_missing: bool = False,
) -> dict:
    """Read the table's Google Sheets tab back. `apply=false` previews the diff;
    `apply=true` commits it (same validation as the Excel upload)."""
    spec = _writable_or_400(_spec_or_404(table))
    access.require_privilege(db, user, spec.privilege)
    try:
        return service.pull_from_sheet(db, spec, apply, delete_missing, user.id)
    except RuntimeError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
