from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.domains.events.schemas import EventBrief
from app.domains.inventory.models import AllocationPurpose, Condition, LocationKind
from app.domains.users.schemas import UserBrief


class AllocationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    quantity: int
    purpose: str
    label: str
    event: EventBrief | None
    event_team_id: int | None = None
    team_name: str | None = None
    display_label: str
    holder: UserBrief | None
    notes: str
    created_at: datetime


class ItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    category: str | None
    asset_tag: str | None
    sku: str | None
    quantity: int  # total owned
    low_stock_threshold: int
    unit: str
    location: str | None
    condition: str
    notes: str
    aliases: str = ""
    team_lead: UserBrief | None
    # computed capacity
    in_use: int
    free: int
    by_purpose: dict[str, int]
    allocations: list[AllocationOut] = []
    # market value (per unit) + where it came from — see models.InventoryItem
    unit_value: float | None = None
    total_value: float | None = None
    value_currency: str | None = None
    value_source: str | None = None
    value_ref: str | None = None
    value_title: str | None = None
    value_url: str | None = None
    value_note: str = ""
    value_checked_at: datetime | None = None
    value_error: str | None = None
    created_at: datetime
    updated_at: datetime


class ItemCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    category: str | None = Field(default=None, max_length=100)
    asset_tag: str | None = Field(default=None, max_length=100)
    sku: str | None = Field(default=None, max_length=100)
    quantity: int = Field(default=1, ge=0)
    low_stock_threshold: int = Field(default=0, ge=0)
    unit: str = Field(default="unit", max_length=30)
    location: str | None = Field(default=None, max_length=255)
    condition: Condition = Condition.GOOD
    notes: str = ""
    aliases: str = ""
    team_lead_id: int | None = None


class ItemEdit(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    category: str | None = Field(default=None, max_length=100)
    asset_tag: str | None = Field(default=None, max_length=100)
    sku: str | None = Field(default=None, max_length=100)
    quantity: int | None = Field(default=None, ge=0)
    low_stock_threshold: int | None = Field(default=None, ge=0)
    unit: str | None = Field(default=None, max_length=30)
    location: str | None = Field(default=None, max_length=255)
    condition: Condition | None = None
    notes: str | None = None
    aliases: str | None = None
    team_lead_id: int | None = None
    clear_team_lead: bool = False


# --- locations & movements (whereabouts) ----------------------------------
class LocationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    kind: str
    notes: str


class LocationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    kind: LocationKind = LocationKind.OTHER
    notes: str = ""


class MovementCreate(BaseModel):
    quantity: int = Field(ge=1)
    from_location_id: int | None = None
    from_holder_id: int | None = None
    to_location_id: int | None = None
    to_holder_id: int | None = None
    reason: str = Field(default="", max_length=255)


class MovementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    quantity: int
    from_location: LocationOut | None
    to_location: LocationOut | None
    from_holder: UserBrief | None
    to_holder: UserBrief | None
    reason: str
    created_at: datetime


class PlaceOnHand(BaseModel):
    location: LocationOut | None = None
    holder: UserBrief | None = None
    quantity: int


class WhereaboutsOut(BaseModel):
    owned: int  # item.quantity — how many the org owns
    tracked: int  # total currently placed in the ledger
    low_stock: bool
    by_location: list[PlaceOnHand] = []
    by_holder: list[PlaceOnHand] = []


class AllocationCreate(BaseModel):
    quantity: int = Field(ge=1)
    purpose: AllocationPurpose = AllocationPurpose.OTHER
    label: str = Field(default="", max_length=255)
    event_id: int | None = None
    event_team_id: int | None = None
    holder_id: int | None = None
    notes: str = ""


class BulkAllocationLine(BaseModel):
    item_id: int
    quantity: int = Field(ge=1)


class BulkAllocationCreate(BaseModel):
    """Allocate several items in one shot with a shared purpose/holder/event."""

    lines: list[BulkAllocationLine] = Field(min_length=1)
    purpose: AllocationPurpose = AllocationPurpose.OTHER
    label: str = Field(default="", max_length=255)
    event_id: int | None = None
    event_team_id: int | None = None
    holder_id: int | None = None
    notes: str = ""


class AllocationEdit(BaseModel):
    quantity: int | None = Field(default=None, ge=1)
    purpose: AllocationPurpose | None = None
    label: str | None = Field(default=None, max_length=255)
    event_id: int | None = None
    clear_event: bool = False
    event_team_id: int | None = None
    clear_team: bool = False
    holder_id: int | None = None
    clear_holder: bool = False
    notes: str | None = None


# --- local file (.xlsx/.csv) import ---------------------------------------
class ImportResult(BaseModel):
    created: int
    updated: int
    skipped: int
    errors: list[str] = []


class FileImportPreviewOut(BaseModel):
    sheets: list[str] | None  # workbook tab names (xlsx); None for CSV
    sheet: str | None  # which tab this preview came from
    headers: list[str]
    rows: list[dict[str, str]]
    total: int


# --- checkout requests (submit -> approve/reject -> issue -> return) ------
class ItemBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    unit: str


class InventoryRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    item: ItemBrief
    requester: UserBrief
    quantity: int
    reason: str
    needed_by: date | None
    return_by: date | None
    status: str
    approver: UserBrief | None
    decision_reason: str
    issued_at: datetime | None
    returned_at: datetime | None
    created_at: datetime
    is_overdue: bool


class InventoryRequestCreate(BaseModel):
    item_id: int
    quantity: int = Field(ge=1)
    reason: str = Field(default="", max_length=1000)
    needed_by: date | None = None
    return_by: date | None = None


class RequestDecision(BaseModel):
    reason: str = Field(default="", max_length=1000)


class RequestIssue(BaseModel):
    from_location_id: int


class RequestReturn(BaseModel):
    to_location_id: int


# --- market value ----------------------------------------------------------
class ValueSet(BaseModel):
    """Pin a shop listing (`source` makers/future + `ref`; the price is fetched
    server-side, never taken from the client) or record a manual estimate
    (`source` manual + `unit_value`)."""

    source: str = Field(pattern="^(makers|future|manual)$")
    ref: str | None = Field(default=None, max_length=255)
    unit_value: float | None = Field(default=None, ge=0)
    note: str = ""


class ValueRefreshOut(BaseModel):
    checked: int
    changed: int
    failed: list[dict]


class ValueSummaryOut(BaseModel):
    currency: str
    total: float  # every priced item, unit value x total quantity owned
    by_source: dict[str, dict]  # source -> {items, units, total}
    priced_items: int
    unpriced_items: int
    unpriced_units: int
    stale_items: int  # pinned listings whose last refresh failed
    other_currencies: dict[str, float]  # should stay empty; never mixed into total
