from datetime import date, datetime, timezone
from enum import StrEnum

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class RequestStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"


class WorkRequest(Base):
    """A request sent up or across the hierarchy to a staff user the requester
    cannot task directly. Accepting spawns a Task owned by the recipient."""

    __tablename__ = "work_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    requester_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    recipient_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    priority: Mapped[str] = mapped_column(String(20), default="medium")
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # optional: this request is for N units of a specific inventory item —
    # informational only (doesn't touch the stock ledger; the recipient can
    # separately use the Inventory > Requests checkout flow to actually issue it)
    item_id: Mapped[int | None] = mapped_column(
        ForeignKey("inventory_items.id", ondelete="SET NULL"), nullable=True, index=True
    )
    quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default=RequestStatus.PENDING, index=True)
    decline_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_task_id: Mapped[int | None] = mapped_column(
        ForeignKey("tasks.id", use_alter=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    requester = relationship("User", foreign_keys=[requester_id], lazy="joined")
    recipient = relationship("User", foreign_keys=[recipient_id], lazy="joined")
    created_task = relationship("Task", foreign_keys=[created_task_id])
    item = relationship("InventoryItem", foreign_keys=[item_id], lazy="joined")
