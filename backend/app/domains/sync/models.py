from datetime import datetime, timezone
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class RebuildStatus(StrEnum):
    DRY_RUN = "dry_run"  # validated, not committed
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class SheetExport(Base):
    """One row per mirrored tab: when it last pushed successfully, its last
    error (if any), and whether it's currently stale (dirty). Surfaced in the
    admin UI so a failed export is visible, never silent."""

    __tablename__ = "sheet_exports"

    id: Mapped[int] = mapped_column(primary_key=True)
    tab: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    is_dirty: Mapped[bool] = mapped_column(Boolean, default=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str] = mapped_column(Text, default="")


class RebuildBatch(Base):
    """One row per Rebuild-from-Sheets attempt (dry-run or committed).
    Append-only — this is the audit trail for the single most destructive
    action in the portal."""

    __tablename__ = "rebuild_batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(20), index=True)
    spreadsheet_id: Mapped[str] = mapped_column(String(255), default="")
    tab_counts: Mapped[str] = mapped_column(Text, default="{}")  # JSON: tab -> row count
    errors: Mapped[str] = mapped_column(Text, default="[]")  # JSON: list of error strings
    snapshot_path: Mapped[str] = mapped_column(String(500), default="")
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    actor = relationship("User", lazy="joined")
