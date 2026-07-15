from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AuditLog(Base):
    """General cross-cutting audit trail: permission changes, inventory
    quantity changes, and competition-role changes. Org-structure changes
    (positions) have their own, richer OrgAuditLog — see app.domains.positions.
    Append-only; nothing here is ever edited or deleted."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    domain: Mapped[str] = mapped_column(String(30), index=True)  # users | inventory | competitions
    action: Mapped[str] = mapped_column(String(50))  # e.g. quantity_changed, pm_added, role_changed
    entity_type: Mapped[str] = mapped_column(String(50))  # e.g. inventory_item, competition, user
    entity_id: Mapped[int | None] = mapped_column(nullable=True, index=True)
    detail: Mapped[str] = mapped_column(Text, default="")  # JSON: before/after/context
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )
