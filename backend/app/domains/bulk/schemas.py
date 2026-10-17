from pydantic import BaseModel


class ApplyRequest(BaseModel):
    rows: list[dict] = []
    deletes: list[int] = []
    # partial=True writes every valid row and reports the rest, instead of the
    # all-or-nothing default (used by the live grid, where one bad cell must not
    # hold back everything else typed around it)
    partial: bool = False
    # return the table's fresh rows after the save (ids, computed columns)
    return_rows: bool = False


class ValidationError(BaseModel):
    row: int | None = None  # index into the submitted rows array (None = whole-table, e.g. a delete)
    column: str | None = None
    message: str
    # code="conflict": the cell changed under the editor — `current` is the
    # value now in the database and `by` who last edited the row
    code: str | None = None
    current: str | None = None
    by: str | None = None


class ApplyResult(BaseModel):
    ok: bool
    errors: list[ValidationError] = []
    summary: dict[str, int] = {}
    # submitted-row index -> id, for every row written (new rows get their id here)
    ids: dict[int, int] = {}
    rows: list[dict] | None = None


class TableSummary(BaseModel):
    key: str
    label: str
    row_count: int
    append_only: bool
    read_only: bool = False
    group: str = "Core"
    description: str = ""
    table: str = ""  # the underlying SQL table name
