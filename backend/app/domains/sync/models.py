from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class SheetExport(Base):
    """One row per mirrored tab: when it last pushed successfully, its last
    error (if any), whether it's currently stale (dirty), and the id set present
    at the last reconcile (the two-way mirror diffs against it)."""

    __tablename__ = "sheet_exports"

    id: Mapped[int] = mapped_column(primary_key=True)
    tab: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    is_dirty: Mapped[bool] = mapped_column(Boolean, default=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str] = mapped_column(Text, default="")
    # JSON list of the row ids present in this tab at the last successful
    # reconcile. The live two-way sync diffs against it to tell an app-created
    # row (id absent here, keep + push) from a sheet-deleted row (id present
    # here, now gone from the sheet -> delete in the DB). See sync.service.
    synced_ids: Mapped[str] = mapped_column(Text, default="[]")
