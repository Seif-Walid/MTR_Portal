"""The data explorer — browse every record the viewer may see and follow how
records connect. Editing goes through the bulk-editor endpoints; this side
only says what the viewer may edit. Board and above (dashboard.view), and each table is
still gated by its domain's view privilege."""

from fastapi import APIRouter, HTTPException, Query, status

from app.domains.access import service as access
from app.domains.auth.deps import DB, CurrentUser
from app.domains.explorer import service

router = APIRouter(prefix="/explore", tags=["explorer"])


def _visible(db: DB, user: CurrentUser) -> set[str]:
    """The dashboard itself needs dashboard.view (Board and above); inside it,
    each kind of record is still gated by its own domain's view privilege."""
    privileges = access.privileges_for(db, user)
    if "dashboard.view" not in privileges:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "The data dashboard is for Board and above")
    return service.visible_tables(privileges)


def _entity(table: str, visible: set[str]) -> service.Entity:
    entity = service.BY_TABLE.get(table)
    if entity is None or table not in visible:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown table")
    return entity


@router.get("/schema")
def schema(db: DB, user: CurrentUser) -> dict:
    """Every kind of record the viewer may see, with counts, and the relations between them."""
    visible = _visible(db, user)
    return service.schema(db, visible, service.edit_keys(access.privileges_for(db, user)))


@router.get("/search")
def search(db: DB, user: CurrentUser, q: str = Query(min_length=1, max_length=100)) -> list[dict]:
    return service.search(db, q.strip(), _visible(db, user), privileges=access.privileges_for(db, user))


@router.get("/{table}")
def list_rows(
    table: str, db: DB, user: CurrentUser,
    q: str = "", offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200),
) -> dict:
    visible = _visible(db, user)
    return service.list_rows(db, _entity(table, visible), q.strip(), offset, limit, visible,
                             access.privileges_for(db, user))


@router.get("/{table}/{record_id}")
def get_record(table: str, record_id: int, db: DB, user: CurrentUser) -> dict:
    visible = _visible(db, user)
    out = service.record(db, _entity(table, visible), record_id, visible, access.privileges_for(db, user))
    if out is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Record not found")
    return service.annotate_edit(out, service.edit_keys(access.privileges_for(db, user)), visible)
