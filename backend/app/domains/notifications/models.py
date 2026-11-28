from datetime import datetime, timezone
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class NotificationType(StrEnum):
    TASK_ASSIGNED = "task_assigned"
    TASK_STATUS_CHANGED = "task_status_changed"
    TASK_COMMENT = "task_comment"
    REQUEST_RECEIVED = "request_received"
    REQUEST_ACCEPTED = "request_accepted"
    REQUEST_DECLINED = "request_declined"
    APPLICATION_RECEIVED = "application_received"


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    type: Mapped[str] = mapped_column(String(40))
    message: Mapped[str] = mapped_column(Text)
    task_id: Mapped[int | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), nullable=True
    )
    request_id: Mapped[int | None] = mapped_column(
        ForeignKey("work_requests.id", ondelete="CASCADE"), nullable=True
    )
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class PushSubscription(Base):
    """One browser/device that asked for push notifications (Web Push).

    `origin` is the portal address the device subscribed on. A server only
    pushes to devices of its own origin, so a staging copy of the prod
    database never pings real people's phones."""

    __tablename__ = "push_subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    endpoint: Mapped[str] = mapped_column(Text, unique=True)
    p256dh: Mapped[str] = mapped_column(String(200))
    auth: Mapped[str] = mapped_column(String(100))
    origin: Mapped[str] = mapped_column(String(200))
    device: Mapped[str] = mapped_column(String(120), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PushKey(Base):
    """The server's Web Push (VAPID) signing key pair, made on first use so a
    deploy needs no extra secrets. Single row, id = 1."""

    __tablename__ = "push_keys"

    id: Mapped[int] = mapped_column(primary_key=True)
    private_pem: Mapped[str] = mapped_column(Text)
    public_key: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
