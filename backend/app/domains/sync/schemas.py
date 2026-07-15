from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SheetExportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tab: str
    row_count: int
    is_dirty: bool
    last_synced_at: datetime | None
    last_error: str


class RebuildReport(BaseModel):
    """Result of a dry-run or a commit: what was read, what would fail (or did
    fail), and — on a successful commit — what actually happened."""

    ok: bool
    tab_counts: dict[str, int]
    errors: list[str]
    would_delete: dict[str, int] = {}  # only populated for a dry-run
    committed: bool = False
    snapshot_path: str | None = None
    batch_id: int | None = None


class RebuildCommitRequest(BaseModel):
    spreadsheet_id: str
    worksheet_prefix: str = ""  # optional, if tabs are prefixed
    confirm_phrase: str


class RebuildBatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    tab_counts: str
    errors: str
    snapshot_path: str
    started_at: datetime
    finished_at: datetime | None
