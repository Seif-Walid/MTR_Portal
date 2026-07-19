import json

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from app.core import gsheets
from app.core.config import settings
from app.domains.access import service as access
from app.domains.auth.deps import DB, CurrentUser
from app.domains.sync import service
from app.domains.sync.models import RebuildBatch
from app.domains.sync.schemas import (
    RebuildBatchOut,
    RebuildCommitRequest,
    RebuildReport,
    SheetExportOut,
)

router = APIRouter(prefix="/sync", tags=["sync"])




class ExportRequest(BaseModel):
    spreadsheet_id: str
    tab: str | None = None  # omit to export every tab


class DryRunRequest(BaseModel):
    spreadsheet_id: str


@router.get("/status")
def sync_status(db: DB, user: CurrentUser) -> dict[str, bool | str]:
    return {"credentials": gsheets.credentials_available(), "org_name": settings.org_name}


@router.get("/exports")
def list_exports(db: DB, user: CurrentUser) -> list[SheetExportOut]:
    access.require_privilege(db, user, "sync.export")
    return [SheetExportOut.model_validate(r) for r in service.list_exports(db)]


@router.post("/export")
def run_export(payload: ExportRequest, db: DB, user: CurrentUser) -> dict[str, int]:
    access.require_privilege(db, user, "sync.export")
    if not gsheets.credentials_available():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Google Sheets is not configured on the server.")
    spreadsheet_id = gsheets.parse_spreadsheet_id(payload.spreadsheet_id)
    try:
        if payload.tab:
            if payload.tab not in service.TAB_ORDER:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown tab '{payload.tab}'")
            return {payload.tab: service.export_tab(db, spreadsheet_id, payload.tab)}
        return service.export_all(db, spreadsheet_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Export failed: {exc}") from exc


@router.post("/rebuild/dry-run")
def rebuild_dry_run(payload: DryRunRequest, db: DB, user: CurrentUser) -> RebuildReport:
    """Read + validate every tab. Never touches the database."""
    access.require_privilege(db, user, "sync.rebuild")
    if not gsheets.credentials_available():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Google Sheets is not configured on the server.")
    spreadsheet_id = gsheets.parse_spreadsheet_id(payload.spreadsheet_id)
    try:
        counts, errors = service.dry_run(db, spreadsheet_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Could not read the sheet: {exc}") from exc
    return RebuildReport(ok=not errors, tab_counts=counts, errors=errors)


@router.post("/rebuild/commit")
def rebuild_commit(payload: RebuildCommitRequest, db: DB, user: CurrentUser) -> RebuildReport:
    """The destructive path. Admin/CEO only. Requires typing the exact
    confirmation phrase. Always re-validates before touching anything —
    a dry-run that failed cannot be forced through."""
    access.require_privilege(db, user, "sync.rebuild")
    if payload.confirm_phrase != settings.org_name:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Type '{settings.org_name}' exactly to confirm this destroys and rebuilds the database.",
        )
    if not gsheets.credentials_available():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Google Sheets is not configured on the server.")
    spreadsheet_id = gsheets.parse_spreadsheet_id(payload.spreadsheet_id)
    try:
        batch = service.commit_rebuild(db, spreadsheet_id, user.id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Rebuild failed: {exc}") from exc

    return RebuildReport(
        ok=batch.status == "succeeded",
        tab_counts=json.loads(batch.tab_counts),
        errors=json.loads(batch.errors),
        committed=batch.status == "succeeded",
        snapshot_path=batch.snapshot_path or None,
        batch_id=batch.id,
    )


@router.get("/rebuild/history")
def rebuild_history(db: DB, user: CurrentUser, limit: int = 20) -> list[RebuildBatchOut]:
    access.require_privilege(db, user, "sync.rebuild")
    rows = db.scalars(select(RebuildBatch).order_by(RebuildBatch.started_at.desc()).limit(min(limit, 100)))
    return [RebuildBatchOut.model_validate(r) for r in rows]
