from datetime import date, datetime, timezone
from enum import StrEnum

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class TaskStatus(StrEnum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    SUBMITTED = "submitted"  # submitted for review
    APPROVED = "approved"
    REVISION_REQUESTED = "revision_requested"


class TaskPriority(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    assigner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    assignee_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    priority: Mapped[str] = mapped_column(String(20), default=TaskPriority.MEDIUM)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default=TaskStatus.TODO, index=True)
    origin_request_id: Mapped[int | None] = mapped_column(
        ForeignKey("work_requests.id", use_alter=True), nullable=True
    )
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    blocked_reason: Mapped[str] = mapped_column(Text, default="")
    # set only when this task was created alongside sibling tasks in one
    # multi-assignee "team assignment" — null for ordinary single-assignee tasks
    batch_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    # set when the task was assigned in an event-team context — null for
    # ordinary org/permanent-team tasks. Drives team-scoped visibility and,
    # once the event is archived (or the team soft-deleted), archival: an
    # archived task derives entirely from this link, never a stored flag.
    event_team_id: Mapped[int | None] = mapped_column(
        ForeignKey("event_teams.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # assigner's choice: when True, every member of event_team_id may view the
    # task (a shared team board); when False, only assigner + assignee see it.
    team_visible: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    assigner = relationship("User", foreign_keys=[assigner_id], lazy="joined")
    assignee = relationship("User", foreign_keys=[assignee_id], lazy="joined")
    attachments: Mapped[list["TaskAttachment"]] = relationship(
        back_populates="task", lazy="selectin", cascade="all, delete-orphan"
    )
    comments: Mapped[list["TaskComment"]] = relationship(
        back_populates="task",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="TaskComment.created_at",
    )


class TaskAttachment(Base):
    __tablename__ = "task_attachments"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), index=True
    )
    filename: Mapped[str] = mapped_column(String(255))
    stored_name: Mapped[str] = mapped_column(String(255), unique=True)
    content_type: Mapped[str] = mapped_column(String(120), default="application/octet-stream")
    size: Mapped[int] = mapped_column(Integer, default=0)
    uploaded_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    task: Mapped[Task] = relationship(back_populates="attachments")


class TaskComment(Base):
    __tablename__ = "task_comments"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), index=True
    )
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    task: Mapped[Task] = relationship(back_populates="comments")
    author = relationship("User", lazy="joined")
