from fastapi import APIRouter, File, HTTPException, Response, UploadFile, status
from sqlalchemy import func, select

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
    spec = _spec_or_404(table)
    access.require_privilege(db, user, spec.privilege)
    return service.read_table(db, spec)


@router.get("/{table}/trash")
def get_trash(table: str, db: DB, user: CurrentUser) -> list[dict]:
    spec = _writable_or_400(_spec_or_404(table))
    access.require_privilege(db, user, spec.privilege)
    return service.trash(db, spec)


@router.post("/{table}/restore/{audit_id}")
def restore_row(table: str, audit_id: int, db: DB, user: CurrentUser) -> dict:
    spec = _writable_or_400(_spec_or_404(table))
    access.require_privilege(db, user, spec.privilege)
    result = service.restore(db, spec, audit_id, user.id)
    if not result["ok"]:
        raise HTTPException(status.HTTP_409_CONFLICT, result["message"])
    return result


@router.get("/{table}/{row_id}/history")
def get_history(table: str, row_id: int, db: DB, user: CurrentUser) -> list[dict]:
    spec = _spec_or_404(table)
    access.require_privilege(db, user, spec.privilege)
    return service.row_history(db, spec, row_id)


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
    result = service.apply(db, spec, payload.rows, payload.deletes, user.id, partial=payload.partial)
    if payload.return_rows:
        result["rows"] = service.table_rows(db, spec)
    return ApplyResult(**result)


@router.get("/{table}/export.xlsx")
def export_xlsx(table: str, db: DB, user: CurrentUser) -> Response:
    """Download the whole table as a real .xlsx."""
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
    """The edited file comes back here. `apply=false` returns a preview of what
    would change; `apply=true` commits it. `delete_missing` also removes rows the
    user deleted from the file (rows in the DB but absent from it)."""
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
