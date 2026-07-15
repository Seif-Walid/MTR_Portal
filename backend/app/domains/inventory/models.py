from datetime import date, datetime, timezone
from enum import StrEnum

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Condition(StrEnum):
    NEW = "new"
    GOOD = "good"
    FAIR = "fair"
    POOR = "poor"
    DAMAGED = "damaged"


class LocationKind(StrEnum):
    ROOM = "room"
    SHELF = "shelf"
    BOX = "box"
    OTHER = "other"


class InventoryRequestStatus(StrEnum):
    SUBMITTED = "submitted"
    APPROVED = "approved"
    REJECTED = "rejected"
    ISSUED = "issued"
    RETURNED = "returned"
    # "overdue" is not a stored state — it's issued + past return_by, computed
    # at read time (no background scheduler in this stack; see DECISIONS.md).


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
    sku: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    quantity: Mapped[int] = mapped_column(Integer, default=1)  # total owned
    low_stock_threshold: Mapped[int] = mapped_column(Integer, default=0)
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
    # Soft delete: allocations, stock movements and checkout requests all
    # reference this item — hard-deleting it would cascade-destroy that
    # history. "Deleting" an item marks it here instead; a genuine hard
    # delete is a separate admin-only escape hatch.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

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


class Location(Base):
    """A place stock can live: a room, shelf or box."""

    __tablename__ = "inventory_locations"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    kind: Mapped[str] = mapped_column(String(20), default=LocationKind.OTHER)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class StockMovement(Base):
    """An append-only ledger row: `quantity` units of an item moving from a
    source (a location, a holder, or nowhere = stock-in) to a destination (a
    location, a holder, or nowhere = stock-out/consumed). On-hand is derived by
    summing this table — it is never edited in place."""

    __tablename__ = "inventory_movements"

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(
        ForeignKey("inventory_items.id", ondelete="CASCADE"), index=True
    )
    quantity: Mapped[int] = mapped_column(Integer)
    from_location_id: Mapped[int | None] = mapped_column(
        ForeignKey("inventory_locations.id", ondelete="SET NULL"), nullable=True
    )
    from_holder_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    to_location_id: Mapped[int | None] = mapped_column(
        ForeignKey("inventory_locations.id", ondelete="SET NULL"), nullable=True
    )
    to_holder_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    actor_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reason: Mapped[str] = mapped_column(String(255), default="")
    # set when this movement was created by issuing/returning a request
    request_id: Mapped[int | None] = mapped_column(
        ForeignKey("inventory_requests.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )

    item = relationship("InventoryItem", lazy="joined")
    from_location = relationship("Location", foreign_keys=[from_location_id], lazy="joined")
    to_location = relationship("Location", foreign_keys=[to_location_id], lazy="joined")
    from_holder = relationship("User", foreign_keys=[from_holder_id], lazy="joined")
    to_holder = relationship("User", foreign_keys=[to_holder_id], lazy="joined")


class InventoryRequest(Base):
    """A checkout request: items + quantity + reason + needed-by/return-by.
    submitted -> approved/rejected -> issued -> returned. Issuing/returning is
    the only path that creates the underlying StockMovement — no side-door
    edits to whereabouts."""

    __tablename__ = "inventory_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(
        ForeignKey("inventory_items.id", ondelete="CASCADE"), index=True
    )
    requester_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    quantity: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(Text, default="")
    needed_by: Mapped[date | None] = mapped_column(Date, nullable=True)
    return_by: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), default=InventoryRequestStatus.SUBMITTED, index=True
    )
    approver_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    decision_reason: Mapped[str] = mapped_column(Text, default="")
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    returned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )

    item = relationship("InventoryItem", lazy="joined")
    requester = relationship("User", foreign_keys=[requester_id], lazy="joined")
    approver = relationship("User", foreign_keys=[approver_id], lazy="joined")

    @property
    def is_overdue(self) -> bool:
        if self.status != InventoryRequestStatus.ISSUED or self.return_by is None:
            return False
        return date.today() > self.return_by
