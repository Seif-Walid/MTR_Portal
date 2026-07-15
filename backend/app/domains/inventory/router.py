from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.domains.auth.deps import DB, CurrentUser
from app.domains.competitions.models import Competition
from app.domains.inventory import sheets
from app.domains.inventory.models import Condition, InventoryAllocation, InventoryItem
from app.domains.inventory.schemas import (
    AllocationCreate,
    AllocationEdit,
    ImportPreviewOut,
    ImportPreviewRequest,
    ImportRequest,
    ImportResult,
    ItemCreate,
    ItemEdit,
    ItemOut,
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
    require_manage(user)
    users = db.scalars(
        select(User).where(User.is_active).order_by(User.full_name)
    )
    return [UserBrief.model_validate(u) for u in users]


@router.get("/sheets/status")
def sheets_status(user: CurrentUser) -> dict[str, bool]:
    """Google Sheets capabilities: `configured` gates the Sync button (needs a
    default target sheet); `credentials` gates Import (needs only the key)."""
    return {
        "configured": sheets.is_configured(),
        "credentials": sheets.credentials_available(),
        "can_sync": can_manage_inventory(user),
    }


@router.post("/sync")
def sync_to_sheets(db: DB, user: CurrentUser) -> dict[str, object]:
    require_manage(user)
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


@router.post("/import/preview")
def import_preview(payload: ImportPreviewRequest, db: DB, user: CurrentUser) -> ImportPreviewOut:
    """Read a sheet's headers + first rows so the UI can map columns."""
    require_manage(user)
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
    require_manage(user)
    _require_credentials()
    if not payload.mapping.get("name"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Map a column to the item name.")
    team_lead_id = _resolve_user(db, payload.team_lead_id, "Team lead")
    try:
        _, rows = sheets.read_worksheet(payload.spreadsheet_id, payload.worksheet)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Could not read the sheet: {exc}") from exc

    created = updated = skipped = 0
    errors: list[str] = []
    for i, row in enumerate(rows, start=2):  # row 1 is the header
        fields = _row_to_fields(row, payload.mapping)
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
            if not payload.upsert:
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


@router.post("", status_code=status.HTTP_201_CREATED)
def create_item(payload: ItemCreate, db: DB, user: CurrentUser) -> ItemOut:
    require_manage(user)
    item = InventoryItem(
        name=payload.name,
        category=payload.category,
        asset_tag=payload.asset_tag,
        quantity=payload.quantity,
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
    require_manage(user)
    if payload.quantity is not None:
        assert_quantity_covers_allocations(item, payload.quantity)
        item.quantity = payload.quantity
    for field in ("name", "category", "asset_tag", "unit", "location", "condition", "notes"):
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
def delete_item(item_id: int, db: DB, user: CurrentUser) -> None:
    item = get_item_or_404(db, user, item_id)
    require_manage(user)
    db.delete(item)
    db.commit()


# --- allocations ----------------------------------------------------------
@router.post("/{item_id}/allocations", status_code=status.HTTP_201_CREATED)
def add_allocation(
    item_id: int, payload: AllocationCreate, db: DB, user: CurrentUser
) -> ItemOut:
    item = get_item_or_404(db, user, item_id)
    require_manage(user)
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
    require_manage(user)
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
    require_manage(user)
    db.delete(allocation)
    db.commit()
