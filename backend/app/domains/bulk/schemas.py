from pydantic import BaseModel


class ApplyRequest(BaseModel):
    rows: list[dict] = []
    deletes: list[int] = []


class ValidationError(BaseModel):
    row: int | None = None  # index into the submitted rows array (None = whole-table, e.g. a delete)
    column: str | None = None
    message: str


class ApplyResult(BaseModel):
    ok: bool
    errors: list[ValidationError] = []
    summary: dict[str, int] = {}


class TableSummary(BaseModel):
    key: str
    label: str
    row_count: int
    append_only: bool


class SheetWebhookRequest(BaseModel):
    tab: str  # the worksheet/table key, e.g. "inventory_items"
    row: dict = {}  # one row keyed by column name; id blank = insert
