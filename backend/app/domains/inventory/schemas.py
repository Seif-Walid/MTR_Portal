from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.domains.competitions.schemas import CompetitionBrief
from app.domains.inventory.models import AllocationPurpose, Condition
from app.domains.users.schemas import UserBrief


class AllocationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    quantity: int
    purpose: str
    label: str
    competition: CompetitionBrief | None
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
    team_lead: UserBrief | None
    # computed capacity
    in_use: int
    free: int
    by_purpose: dict[str, int]
    allocations: list[AllocationOut] = []
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
    kind: str = Field(default="other", max_length=20)
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
    competition_id: int | None = None
    holder_id: int | None = None
    notes: str = ""


class AllocationEdit(BaseModel):
    quantity: int | None = Field(default=None, ge=1)
    purpose: AllocationPurpose | None = None
    label: str | None = Field(default=None, max_length=255)
    competition_id: int | None = None
    clear_competition: bool = False
    holder_id: int | None = None
    clear_holder: bool = False
    notes: str | None = None


# --- Google Sheet import --------------------------------------------------
class ImportPreviewRequest(BaseModel):
    source: str = Field(min_length=1)  # full Sheet URL or bare spreadsheet id
    worksheet: str | None = None


class ImportPreviewOut(BaseModel):
    spreadsheet_id: str
    worksheet: str | None
    headers: list[str]
    rows: list[dict[str, str]]  # first N rows, for column mapping
    total: int


class ImportRequest(BaseModel):
    spreadsheet_id: str = Field(min_length=1)
    worksheet: str | None = None
    # target item field -> source column header. "name" is required.
    mapping: dict[str, str]
    team_lead_id: int | None = None
    upsert: bool = True  # update existing items (matched by asset tag or name)


class ImportResult(BaseModel):
    created: int
    updated: int
    skipped: int
    errors: list[str] = []


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
