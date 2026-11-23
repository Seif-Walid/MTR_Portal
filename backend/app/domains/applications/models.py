from datetime import datetime, timezone
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class ApplicationStatus(StrEnum):
    NEW = "new"
    CONTACTED = "contacted"
    ACCEPTED = "accepted"
    WAITLISTED = "waitlisted"
    DECLINED = "declined"


class ApplicationSource(StrEnum):
    WEBSITE = "website"  # the site's "Join the team" form
    PORTAL = "portal"  # "Request entry" on the portal's sign-in page


class Application(Base):
    """A join application: from the website's "Join the team" form, or a
    request for entry made on the portal's sign-in page (which is the only way
    to ask for an account — nobody can make one for themselves).

    It stays its own record until someone acts on it: an application is not a
    member, and adding the applicant to the roster (`member_id`) is a separate,
    deliberate step. The applicant's answers are kept exactly as sent; staff
    only ever change `status` and `notes`."""

    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(255), index=True)
    phone: Mapped[str] = mapped_column(String(50))
    school: Mapped[str] = mapped_column(String(255))
    year: Mapped[str] = mapped_column(String(100))
    # NULL = "not sure yet — help me pick"
    subteam: Mapped[str | None] = mapped_column(String(50), nullable=True)
    motivation: Mapped[str] = mapped_column(Text)
    # The event the applicant asked to join from the site (one that was open
    # for applications at the time). NULL = a general "join the team".
    event_id: Mapped[int | None] = mapped_column(
        ForeignKey("events.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source: Mapped[str] = mapped_column(
        String(20), default=ApplicationSource.WEBSITE, server_default=ApplicationSource.WEBSITE.value
    )
    # Entry requests only: the hash of the password the person chose, given
    # to their account when the request is accepted (so they can sign in at
    # once) and dropped as soon as the request is settled either way.
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default=ApplicationStatus.NEW, index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The member (account) this applicant became, or turned out to already be.
    member_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # Salted hash of the sender's IP — enough to rate-limit the public form
    # without keeping anyone's address.
    client_hash: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    reviewed_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    reviewed_by = relationship("User", foreign_keys=[reviewed_by_id], lazy="joined")
    member = relationship("User", foreign_keys=[member_id], lazy="joined")
    event = relationship("Event", lazy="joined")
