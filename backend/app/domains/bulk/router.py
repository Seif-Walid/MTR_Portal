from fastapi import APIRouter, File, HTTPException, Response, UploadFile, status
from sqlalchemy import func, select

from app.domains.access import service as access
from app.domains.auth.deps import DB, CurrentUser
from app.domains.bulk import service
from app.domains.bulk.registry import TABLES, TableSpec
from app.domains.bulk.schemas import ApplyRequest, ApplyResult, TableSummary

XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

router = APIRouter(prefix="/bulk", tags=["bulk"])


def _spec_or_404(table: str) -> TableSpec:
    spec = TABLES.get(table)
    if spec is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown table '{table}'")
    return spec


@router.get("/tables")
def list_tables(db: DB, user: CurrentUser) -> list[TableSummary]:
    """Only the tables this user may edit — each table is gated by its own
    per-domain privilege (inventory.edit, users.manage, ...)."""
    out: list[TableSummary] = []
    for spec in TABLES.values():
        if not access.has_privilege(db, user, spec.privilege):
            continue
        count = db.scalar(select(func.count()).select_from(spec.model)) or 0
        out.append(TableSummary(key=spec.key, label=spec.label, row_count=count,
                                append_only=spec.append_only))
    return out


@router.get("/sheets/status")
def sheets_status(user: CurrentUser) -> dict:
    """Is the Google Sheets round-trip available on this server? Drives the
    enabled state of the 'Open in Google Sheets' / 'Pull from Sheet' buttons."""
    return service.sheet_status()


@router.get("/{table}")
def get_table(table: str, db: DB, user: CurrentUser) -> dict:
    spec = _spec_or_404(table)
    access.require_privilege(db, user, spec.privilege)
    return service.read_table(db, spec)


@router.post("/{table}/validate")
def validate_table(table: str, payload: ApplyRequest, db: DB, user: CurrentUser) -> ApplyResult:
    spec = _spec_or_404(table)
    access.require_privilege(db, user, spec.privilege)
    _, errors, summary = service.validate(db, spec, payload.rows, payload.deletes)
    return ApplyResult(ok=not errors, errors=errors, summary=summary)


@router.post("/{table}")
def apply_table(table: str, payload: ApplyRequest, db: DB, user: CurrentUser) -> ApplyResult:
    spec = _spec_or_404(table)
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
    spec = _spec_or_404(table)
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
    spec = _spec_or_404(table)
    access.require_privilege(db, user, spec.privilege)
    try:
        return service.push_to_sheet(db, spec)
    except RuntimeError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


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
    spec = _spec_or_404(table)
    access.require_privilege(db, user, spec.privilege)
    try:
        return service.pull_from_sheet(db, spec, apply, delete_missing, user.id)
    except RuntimeError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
