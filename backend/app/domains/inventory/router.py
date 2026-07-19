import json
from datetime import datetime, timezone

from fastapi import APIRouter, Form, HTTPException, UploadFile, status
from sqlalchemy import select

from app.core.config import settings
from app.domains.audit.service import log as audit_log
from app.domains.access import service as access
from app.domains.auth.deps import DB, CurrentUser
from app.domains.competitions.models import Competition
from app.domains.inventory import file_import, sheets, stock
from app.domains.inventory.models import (
    Condition,
    InventoryAllocation,
    InventoryItem,
    Location,
    StockMovement,
)
from app.domains.inventory.schemas import (
    AllocationCreate,
    AllocationEdit,
    FileImportPreviewOut,
    ImportPreviewOut,
    ImportPreviewRequest,
    ImportRequest,
    ImportResult,
    ItemBrief,
    ItemCreate,
    ItemEdit,
    ItemOut,
    LocationCreate,
    LocationOut,
    MovementCreate,
    MovementOut,
    PlaceOnHand,
    WhereaboutsOut,
)
from app.domains.inventory.service import (
    assert_fits,
    assert_quantity_covers_allocations,
    can_manage_inventory,
    get_allocation_or_404,
    get_item_or_404,
    require_manage,
    visible_items_query,
)
from app.domains.users.models import User
from app.domains.users.schemas import UserBrief

router = APIRouter(prefix="/inventory", tags=["inventory"])


def _resolve_user(db: DB, user_id: int | None, what: str) -> int | None:
    if user_id is None:
        return None
    if db.get(User, user_id) is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{what} not found")
    return user_id


def _resolve_competition(db: DB, competition_id: int | None) -> int | None:
    if competition_id is None:
        return None
    if db.get(Competition, competition_id) is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Competition not found")
    return competition_id


# --- literal routes (declared before /{item_id}) --------------------------
@router.get("/holders")
def holder_options(db: DB, user: CurrentUser) -> list[UserBrief]:
    """People who can hold equipment. Staff manage org-wide, so they pick from
    all active users."""
    access.require_privilege(db, user, "people.view")
    users = db.scalars(
        select(User).where(User.is_active).order_by(User.full_name)
    )
    return [UserBrief.model_validate(u) for u in users]


@router.get("/directory")
def item_directory(db: DB, user: CurrentUser) -> list[ItemBrief]:
    """Minimal item list (id/name/unit) for pickers — e.g. attaching an item to
    a cross-branch work request. Any signed-in user may read it: a request is
    precisely the mechanism for asking for something outside your normal
    inventory visibility, so this deliberately bypasses that scoping."""
    items = db.scalars(select(InventoryItem).order_by(InventoryItem.name)).unique()
    return [ItemBrief.model_validate(i) for i in items]


@router.get("/sheets/status")
def sheets_status(db: DB, user: CurrentUser) -> dict[str, bool]:
    """Google Sheets capabilities: `configured` gates the Sync button (needs a
    default target sheet); `credentials` gates Import (needs only the key)."""
    return {
        "configured": sheets.is_configured(),
        "credentials": sheets.credentials_available(),
        "can_sync": can_manage_inventory(db, user),
    }


@router.post("/sync")
def sync_to_sheets(db: DB, user: CurrentUser) -> dict[str, object]:
    require_manage(db, user)
    if not sheets.is_configured():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Google Sheets sync is not configured on the server.",
        )
    items = list(db.scalars(select(InventoryItem).order_by(InventoryItem.name)).unique())
    try:
        result = sheets.push_inventory(items)
    except Exception as exc:  # noqa: BLE001 — surface the sync failure to the user
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Sync failed: {exc}") from exc
    return result


# --- import from a Google Sheet ------------------------------------------
def _require_credentials() -> None:
    if not sheets.credentials_available():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Google Sheets is not configured on the server (service-account key missing).",
        )


def _parse_int(value: str, default: int = 1) -> int:
    text = (value or "").strip().replace(",", "")
    try:
        return max(0, int(float(text)))
    except (ValueError, TypeError):
        return default


def _row_to_fields(row: dict[str, str], mapping: dict[str, str]) -> dict:
    def src(field: str) -> str:
        col = mapping.get(field)
        return (row.get(col, "") if col else "").strip()

    condition = src("condition").lower()
    valid_conditions = {c.value for c in Condition}
    return {
        "name": src("name"),
        "category": src("category") or None,
        "asset_tag": src("asset_tag") or None,
        "quantity": _parse_int(src("quantity")) if mapping.get("quantity") else 1,
        "unit": src("unit") or "unit",
        "location": src("location") or None,
        "condition": condition if condition in valid_conditions else Condition.GOOD,
    }


def _import_rows(
    db: DB,
    rows: list[dict[str, str]],
    mapping: dict[str, str],
    team_lead_id: int | None,
    upsert: bool,
) -> ImportResult:
    created = updated = skipped = 0
    errors: list[str] = []
    for row in rows:
        fields = _row_to_fields(row, mapping)
        if not fields["name"]:
            skipped += 1
            continue
        existing = None
        if fields["asset_tag"]:
            existing = db.scalar(
                select(InventoryItem).where(InventoryItem.asset_tag == fields["asset_tag"])
            )
        if existing is None:
            existing = db.scalar(
                select(InventoryItem).where(InventoryItem.name == fields["name"])
            )
        if existing is not None:
            if not upsert:
                skipped += 1
                continue
            for key, value in fields.items():
                setattr(existing, key, value)
            if team_lead_id is not None:
                existing.team_lead_id = team_lead_id
            updated += 1
        else:
            db.add(InventoryItem(**fields, team_lead_id=team_lead_id))
            created += 1
    db.commit()
    return ImportResult(created=created, updated=updated, skipped=skipped, errors=errors)


@router.post("/import/preview")
def import_preview(payload: ImportPreviewRequest, db: DB, user: CurrentUser) -> ImportPreviewOut:
    """Read a sheet's headers + first rows so the UI can map columns."""
    require_manage(db, user)
    _require_credentials()
    spreadsheet_id = sheets.parse_spreadsheet_id(payload.source)
    try:
        headers, rows = sheets.read_worksheet(spreadsheet_id, payload.worksheet)
    except Exception as exc:  # noqa: BLE001 — surface read failures to the user
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Could not read the sheet: {exc}") from exc
    return ImportPreviewOut(
        spreadsheet_id=spreadsheet_id,
        worksheet=payload.worksheet,
        headers=headers,
        rows=rows[:15],
        total=len(rows),
    )


@router.post("/import")
def import_items(payload: ImportRequest, db: DB, user: CurrentUser) -> ImportResult:
    """Create (or upsert) inventory items from a Google Sheet. The portal takes
    over as the source of truth once imported."""
    require_manage(db, user)
    _require_credentials()
    if not payload.mapping.get("name"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Map a column to the item name.")
    team_lead_id = _resolve_user(db, payload.team_lead_id, "Team lead")
    try:
        _, rows = sheets.read_worksheet(payload.spreadsheet_id, payload.worksheet)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Could not read the sheet: {exc}") from exc
    return _import_rows(db, rows, payload.mapping, team_lead_id, payload.upsert)


def _read_upload(file: UploadFile) -> bytes:
    data = file.file.read(settings.max_upload_mb * 1024 * 1024 + 1)
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"File exceeds {settings.max_upload_mb} MB limit",
        )
    return data


@router.post("/import/file/preview")
def import_file_preview(
    db: DB,
    user: CurrentUser,
    file: UploadFile,
    sheet: str | None = Form(None),
) -> FileImportPreviewOut:
    """Read an uploaded .xlsx/.csv's headers + first rows — no Google Sheets
    credentials needed. For workbooks with multiple tabs, omit `sheet` to get
    the first one plus the full tab list, then re-call with a chosen tab."""
    require_manage(db, user)
    data = _read_upload(file)
    try:
        sheet_names = file_import.list_sheets(data, file.filename or "")
        chosen, headers, rows = file_import.read_uploaded(data, file.filename or "", sheet)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return FileImportPreviewOut(
        sheets=sheet_names,
        sheet=chosen,
        headers=headers,
        rows=rows[:15],
        total=len(rows),
    )


@router.post("/import/file")
def import_file(
    db: DB,
    user: CurrentUser,
    file: UploadFile,
    mapping: str = Form(...),
    sheet: str | None = Form(None),
    team_lead_id: int | None = Form(None),
    upsert: bool = Form(True),
) -> ImportResult:
    """Create (or upsert) inventory items from an uploaded .xlsx/.csv."""
    require_manage(db, user)
    try:
        mapping_dict = json.loads(mapping)
    except json.JSONDecodeError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid column mapping") from exc
    if not isinstance(mapping_dict, dict) or not mapping_dict.get("name"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Map a column to the item name.")
    resolved_lead_id = _resolve_user(db, team_lead_id, "Team lead")
    data = _read_upload(file)
    try:
        _, _, rows = file_import.read_uploaded(data, file.filename or "", sheet)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return _import_rows(db, rows, mapping_dict, resolved_lead_id, upsert)


# --- locations (whereabouts) ----------------------------------------------
@router.get("/locations")
def list_locations(db: DB, user: CurrentUser) -> list[LocationOut]:
    return [LocationOut.model_validate(loc) for loc in db.scalars(select(Location).order_by(Location.name))]


@router.post("/locations", status_code=status.HTTP_201_CREATED)
def create_location(payload: LocationCreate, db: DB, user: CurrentUser) -> LocationOut:
    require_manage(db, user)
    loc = Location(name=payload.name, kind=payload.kind, notes=payload.notes)
    db.add(loc)
    db.commit()
    db.refresh(loc)
    return LocationOut.model_validate(loc)


@router.delete("/locations/{location_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_location(location_id: int, db: DB, user: CurrentUser) -> None:
    require_manage(db, user)
    loc = db.get(Location, location_id)
    if loc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Location not found")
    db.delete(loc)
    db.commit()


# --- items ----------------------------------------------------------------
@router.get("")
def list_items(
    db: DB,
    user: CurrentUser,
    category: str | None = None,
) -> list[ItemOut]:
    query = visible_items_query(db, user)
    if category:
        query = query.where(InventoryItem.category == category)
    items = db.scalars(query.order_by(InventoryItem.name)).unique()
    return [ItemOut.model_validate(i) for i in items]


@router.get("/low-stock")
def low_stock_items(db: DB, user: CurrentUser) -> list[ItemOut]:
    """Items whose owned quantity has dropped to (or below) their threshold."""
    access.require_privilege(db, user, "inventory.view")
    items = db.scalars(visible_items_query(db, user).order_by(InventoryItem.name)).unique()
    return [ItemOut.model_validate(i) for i in items if i.quantity <= i.low_stock_threshold]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_item(payload: ItemCreate, db: DB, user: CurrentUser) -> ItemOut:
    require_manage(db, user)
    item = InventoryItem(
        name=payload.name,
        category=payload.category,
        asset_tag=payload.asset_tag,
        sku=payload.sku,
        quantity=payload.quantity,
        low_stock_threshold=payload.low_stock_threshold,
        unit=payload.unit,
        location=payload.location,
        condition=payload.condition,
        notes=payload.notes,
        team_lead_id=_resolve_user(db, payload.team_lead_id, "Team lead"),
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return ItemOut.model_validate(item)


@router.get("/{item_id}")
def get_item(item_id: int, db: DB, user: CurrentUser) -> ItemOut:
    return ItemOut.model_validate(get_item_or_404(db, user, item_id))


@router.patch("/{item_id}")
def edit_item(item_id: int, payload: ItemEdit, db: DB, user: CurrentUser) -> ItemOut:
    item = get_item_or_404(db, user, item_id)
    require_manage(db, user)
    if payload.quantity is not None and payload.quantity != item.quantity:
        assert_quantity_covers_allocations(item, payload.quantity)
        audit_log(db, user.id, "inventory", "quantity_changed", "inventory_item", item.id,
                  {"name": item.name, "before": item.quantity, "after": payload.quantity})
        item.quantity = payload.quantity
    for field in ("name", "category", "asset_tag", "sku", "low_stock_threshold",
                  "unit", "location", "condition", "notes"):
        value = getattr(payload, field)
        if value is not None:
            setattr(item, field, value)
    if payload.clear_team_lead:
        item.team_lead_id = None
    elif payload.team_lead_id is not None:
        item.team_lead_id = _resolve_user(db, payload.team_lead_id, "Team lead")
    db.commit()
    db.refresh(item)
    return ItemOut.model_validate(item)


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_item(item_id: int, db: DB, user: CurrentUser, permanent: bool = False) -> None:
    """Soft-deletes by default: allocations, movements and requests all
    reference this item, so removing the row would destroy their history.
    `permanent=true` really removes it — a genuine mistake, admin only."""
    item = get_item_or_404(db, user, item_id)
    require_manage(db, user)
    if permanent:
        if not access.is_top(db, user):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "Only a top-level user can permanently delete an item"
            )
        audit_log(db, user.id, "inventory", "item_purged", "inventory_item", item.id,
                  {"name": item.name})
        db.delete(item)
    else:
        audit_log(db, user.id, "inventory", "item_deleted", "inventory_item", item.id,
                  {"name": item.name})
        item.deleted_at = datetime.now(timezone.utc)
    db.commit()


# --- allocations ----------------------------------------------------------
@router.post("/{item_id}/allocations", status_code=status.HTTP_201_CREATED)
def add_allocation(
    item_id: int, payload: AllocationCreate, db: DB, user: CurrentUser
) -> ItemOut:
    item = get_item_or_404(db, user, item_id)
    require_manage(db, user)
    assert_fits(item, payload.quantity)
    allocation = InventoryAllocation(
        item_id=item.id,
        quantity=payload.quantity,
        purpose=payload.purpose,
        label=payload.label,
        competition_id=_resolve_competition(db, payload.competition_id),
        holder_id=_resolve_user(db, payload.holder_id, "Holder"),
        notes=payload.notes,
    )
    db.add(allocation)
    db.commit()
    db.refresh(item)
    return ItemOut.model_validate(item)


@router.patch("/allocations/{allocation_id}")
def edit_allocation(
    allocation_id: int, payload: AllocationEdit, db: DB, user: CurrentUser
) -> ItemOut:
    allocation = get_allocation_or_404(db, user, allocation_id)
    require_manage(db, user)
    item = allocation.item
    if payload.quantity is not None:
        assert_fits(item, payload.quantity, exclude_id=allocation.id)
        allocation.quantity = payload.quantity
    if payload.purpose is not None:
        allocation.purpose = payload.purpose
    if payload.label is not None:
        allocation.label = payload.label
    if payload.notes is not None:
        allocation.notes = payload.notes
    if payload.clear_competition:
        allocation.competition_id = None
    elif payload.competition_id is not None:
        allocation.competition_id = _resolve_competition(db, payload.competition_id)
    if payload.clear_holder:
        allocation.holder_id = None
    elif payload.holder_id is not None:
        allocation.holder_id = _resolve_user(db, payload.holder_id, "Holder")
    db.commit()
    db.refresh(item)
    return ItemOut.model_validate(item)


@router.delete("/allocations/{allocation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_allocation(allocation_id: int, db: DB, user: CurrentUser) -> None:
    allocation = get_allocation_or_404(db, user, allocation_id)
    require_manage(db, user)
    db.delete(allocation)
    db.commit()


# --- whereabouts & movements (stock ledger) -------------------------------
def _place_list(db: DB, ids_qty: dict[int, int], kind: str) -> list[PlaceOnHand]:
    out = []
    for oid, qty in sorted(ids_qty.items(), key=lambda kv: -kv[1]):
        if kind == "location":
            loc = db.get(Location, oid)
            out.append(PlaceOnHand(location=LocationOut.model_validate(loc) if loc else None, quantity=qty))
        else:
            holder = db.get(User, oid)
            out.append(PlaceOnHand(holder=UserBrief.model_validate(holder) if holder else None, quantity=qty))
    return out


@router.get("/{item_id}/whereabouts")
def item_whereabouts(item_id: int, db: DB, user: CurrentUser) -> WhereaboutsOut:
    item = get_item_or_404(db, user, item_id)
    by_location, by_holder, tracked = stock.whereabouts(db, item.id)
    return WhereaboutsOut(
        owned=item.quantity,
        tracked=tracked,
        low_stock=item.quantity <= item.low_stock_threshold,
        by_location=_place_list(db, by_location, "location"),
        by_holder=_place_list(db, by_holder, "holder"),
    )


@router.get("/{item_id}/movements")
def item_movements(item_id: int, db: DB, user: CurrentUser, limit: int = 100) -> list[MovementOut]:
    get_item_or_404(db, user, item_id)
    rows = db.scalars(
        select(StockMovement)
        .where(StockMovement.item_id == item_id)
        .order_by(StockMovement.created_at.desc())
        .limit(min(limit, 500))
    )
    return [MovementOut.model_validate(m) for m in rows]


@router.post("/{item_id}/movements", status_code=status.HTTP_201_CREATED)
def add_movement(item_id: int, payload: MovementCreate, db: DB, user: CurrentUser) -> WhereaboutsOut:
    item = get_item_or_404(db, user, item_id)
    access.require_privilege(db, user, "inventory.approve")
    for uid in (payload.from_holder_id, payload.to_holder_id):
        _resolve_user(db, uid, "Holder") if uid else None
    for lid in (payload.from_location_id, payload.to_location_id):
        if lid is not None and db.get(Location, lid) is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Location not found")
    stock.record_movement(
        db, item, payload.quantity,
        from_location_id=payload.from_location_id, from_holder_id=payload.from_holder_id,
        to_location_id=payload.to_location_id, to_holder_id=payload.to_holder_id,
        actor_id=user.id, reason=payload.reason,
    )
    db.commit()
    by_location, by_holder, tracked = stock.whereabouts(db, item.id)
    return WhereaboutsOut(
        owned=item.quantity, tracked=tracked,
        low_stock=item.quantity <= item.low_stock_threshold,
        by_location=_place_list(db, by_location, "location"),
        by_holder=_place_list(db, by_holder, "holder"),
    )
