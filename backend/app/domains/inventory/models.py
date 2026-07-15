from datetime import datetime, timezone
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Condition(StrEnum):
    NEW = "new"
    GOOD = "good"
    FAIR = "fair"
    POOR = "poor"
    DAMAGED = "damaged"


class AllocationPurpose(StrEnum):
    """Why a chunk of an item's pool is currently checked out. `COMPETITION`
    and `RESEARCH` chunks usually also carry a free-text label naming the
    specific competition or project."""

    TRAINING = "training"
    COMPETITION = "competition"
    RESEARCH = "research"  # R&D
    BORROWED = "borrowed"
    OTHER = "other"


class InventoryItem(Base):
    __tablename__ = "inventory_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    asset_tag: Mapped[str | None] = mapped_column(String(100), nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, default=1)  # total pool
    unit: Mapped[str] = mapped_column(String(30), default="unit")
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    condition: Mapped[str] = mapped_column(String(20), default=Condition.GOOD)
    notes: Mapped[str] = mapped_column(Text, default="")
    # Designation: the team lead this equipment is dedicated to. NULL = general
    # storage, visible only to staff. Non-staff members see an item only when
    # its team_lead sits on their manager chain.
    team_lead_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    team_lead = relationship("User", foreign_keys=[team_lead_id], lazy="joined")
    allocations: Mapped[list["InventoryAllocation"]] = relationship(
        back_populates="item", lazy="selectin", cascade="all, delete-orphan"
    )

    # --- computed capacity -------------------------------------------------
    @property
    def in_use(self) -> int:
        return sum(a.quantity for a in self.allocations)

    @property
    def free(self) -> int:
        return self.quantity - self.in_use

    @property
    def by_purpose(self) -> dict[str, int]:
        """Units in use grouped by purpose — the hover breakdown."""
        totals: dict[str, int] = {}
        for a in self.allocations:
            totals[a.purpose] = totals.get(a.purpose, 0) + a.quantity
        return totals


class InventoryAllocation(Base):
    __tablename__ = "inventory_allocations"

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(
        ForeignKey("inventory_items.id", ondelete="CASCADE"), index=True
    )
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    purpose: Mapped[str] = mapped_column(String(20), default=AllocationPurpose.OTHER)
    label: Mapped[str] = mapped_column(String(255), default="")  # free-text (non-competition)
    # For competition-purpose allocations: link to a first-class Competition.
    # When set, its name is the display label everywhere.
    competition_id: Mapped[int | None] = mapped_column(
        ForeignKey("competitions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Who physically holds these units (optional — a chunk can be assigned to a
    # purpose without a named holder, e.g. a general training pool).
    holder_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    item: Mapped[InventoryItem] = relationship(back_populates="allocations")
    holder = relationship("User", foreign_keys=[holder_id], lazy="joined")
    competition = relationship("Competition", lazy="joined")

    @property
    def display_label(self) -> str:
        """Competition name takes precedence over the free-text label."""
        if self.competition is not None:
            return self.competition.name
        return self.label
