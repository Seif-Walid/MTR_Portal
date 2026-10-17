import json

from fastapi import APIRouter, File, Form, HTTPException, Request, Response, UploadFile, status
from sqlalchemy import func, select

from app.core.config import settings
from app.domains.access import service as access
from app.domains.auth.deps import DB, CurrentUser
from app.domains.bulk import service
from app.domains.bulk.registry import TABLES, TableSpec, ensure_all_tables_registered
from app.domains.bulk.schemas import (
    ApplyRequest,
    ApplyResult,
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


def _authorized(db, user, spec: TableSpec) -> TableSpec:
    """Check the table's privilege and narrow it to the columns this viewer may see."""
    access.require_privilege(db, user, spec.privilege)
    return spec.for_privileges(access.privileges_for(db, user))


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
        count = db.scalar(select(func.count()).select_from(spec.model).where(*spec.filters())) or 0
        out.append(TableSummary(key=spec.key, label=spec.label, row_count=count,
                                append_only=spec.append_only, read_only=spec.read_only,
                                group=spec.group, description=spec.description,
                                table=spec.model.__table__.name))
    return out


@router.get("/{table}")
def get_table(table: str, db: DB, user: CurrentUser) -> dict:
    spec = _authorized(db, user, _spec_or_404(table))
    return service.read_table(db, spec)


@router.get("/{table}/trash")
def get_trash(table: str, db: DB, user: CurrentUser) -> list[dict]:
    spec = _authorized(db, user, _writable_or_400(_spec_or_404(table)))
    return service.trash(db, spec)


@router.post("/{table}/restore/{audit_id}")
def restore_row(table: str, audit_id: int, db: DB, user: CurrentUser) -> dict:
    spec = _authorized(db, user, _writable_or_400(_spec_or_404(table)))
    result = service.restore(db, spec, audit_id, user.id)
    if not result["ok"]:
        raise HTTPException(status.HTTP_409_CONFLICT, result["message"])
    return result


@router.get("/{table}/{row_id}/history")
def get_history(table: str, row_id: int, db: DB, user: CurrentUser) -> list[dict]:
    spec = _authorized(db, user, _spec_or_404(table))
    return service.row_history(db, spec, row_id)


@router.post("/{table}/validate")
def validate_table(table: str, payload: ApplyRequest, db: DB, user: CurrentUser) -> ApplyResult:
    spec = _authorized(db, user, _writable_or_400(_spec_or_404(table)))
    _, errors, summary = service.validate(db, spec, payload.rows, payload.deletes)
    return ApplyResult(ok=not errors, errors=errors, summary=summary)


@router.post("/{table}")
def apply_table(table: str, payload: ApplyRequest, db: DB, user: CurrentUser) -> ApplyResult:
    spec = _authorized(db, user, _writable_or_400(_spec_or_404(table)))
    result = service.apply(db, spec, payload.rows, payload.deletes, user.id, partial=payload.partial)
    if payload.return_rows:
        result["rows"] = service.table_rows(db, spec)
    return ApplyResult(**result)


def _scope(request: Request, spec: TableSpec) -> dict[str, str]:
    """Fixed column values passed as query params (e.g. ?season_id=3) — the
    slice of the table a grid shows, so its file covers just that slice."""
    return {k: v for k, v in request.query_params.items() if spec.column(k) is not None}


@router.get("/{table}/export.xlsx")
def export_xlsx(table: str, request: Request, db: DB, user: CurrentUser) -> Response:
    """Download the table (or the grid's slice of it) as a real .xlsx."""
    spec = _authorized(db, user, _spec_or_404(table))
    body = service.workbook_bytes(db, spec, _scope(request, spec))
    return Response(
        content=body,
        media_type=XLSX_MEDIA,
        headers={"Content-Disposition": f'attachment; filename="{spec.key}.xlsx"'},
    )


async def _read_capped(file: UploadFile) -> bytes:
    limit = settings.max_upload_mb * 1024 * 1024
    content = await file.read(limit + 1)
    if len(content) > limit:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, f"File exceeds the {settings.max_upload_mb} MB limit")
    return content


@router.post("/{table}/upload", response_model=None)
async def upload_xlsx(
    table: str,
    request: Request,
    db: DB,
    user: CurrentUser,
    file: UploadFile = File(...),
    apply: bool = False,
    delete_missing: bool = False,
    mapping: str = Form(""),
    annotate: bool = False,
) -> dict | Response:
    """The edited file comes back here. `apply=false` returns a preview of what
    would change; `apply=true` commits it (all-or-nothing). `delete_missing`
    also removes rows of the file's scope that the user deleted from it.
    `mapping` is a JSON {file header: column} for headers that didn't match;
    `annotate=true` returns the file with its Status column filled in."""
    spec = _authorized(db, user, _writable_or_400(_spec_or_404(table)))
    content = await _read_capped(file)
    try:
        chosen = json.loads(mapping) if mapping else {}
        up = service.parse_upload(content, file.filename or "", spec, chosen if isinstance(chosen, dict) else {})
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    fixed = {k: v for k, v in _scope(request, spec).items() if k not in ("apply", "delete_missing", "annotate")}
    scope = {**up.scope, **fixed}
    rows = service.prepare_upload(db, spec, up, fixed)
    plan = service.plan_upload(db, spec, rows, delete_missing, scope)
    for e in plan["errors"]:  # point at the line in the user's own sheet
        if e.get("row") is not None and e["row"] < len(up.lines):
            e["line"] = up.lines[e["row"]]
    if annotate:
        body = service.annotated_workbook(content, file.filename or "", up, plan["errors"])
        name = (file.filename or spec.key).rsplit(".", 1)[0]
        return Response(content=body, media_type=XLSX_MEDIA,
                        headers={"Content-Disposition": f'attachment; filename="{name} - checked.xlsx"'})
    info = {
        "columns": [{"name": c.name, "label": c.header} for c in spec.columns if c.editable],
        "matched": up.matched,
        "unmatched": up.unmatched,
        "template": up.base is not None,
        "scope": scope,
        "row_count": len(rows),
    }
    if not apply or not plan["ok"]:
        return {"applied": False, **plan, **info}
    deletes = plan["missing_ids"] if (delete_missing and plan["can_delete"]) else []
    result = service.apply(db, spec, rows, deletes, user.id)
    return {"applied": result["ok"], **result, **info, "new": plan["new"], "changed": plan["changed"],
            "will_delete": len(deletes)}
