from datetime import date, datetime, timezone
from enum import StrEnum

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Department(StrEnum):
    SOFTWARE = "software"
    MECHANICAL = "mechanical"
    ELECTRICAL = "electrical"
    MEDIA = "media"
    FINANCE = "finance"


class User(Base):
    """An account. What a person can *do* is decided entirely by the access
    ladder (see app/domains/access): their effective level is the strongest
    of the org seats they occupy plus the personal override below — there is
    no role list and no hardcoded job name anywhere. `manager_id` remains the
    structural reporting line (task subtree, visibility)."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(255))
    hashed_password: Mapped[str] = mapped_column(String(255))
    department: Mapped[str | None] = mapped_column(String(50), nullable=True)
    manager_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Personal access-level override — power granted directly to the person,
    # independent of any seat (bootstrap admin, an advisor with no position).
    access_level_id: Mapped[int | None] = mapped_column(
        ForeignKey("access_levels.id", ondelete="SET NULL"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Set the first time this account is explicitly linked to a Google
    # identity (see app.domains.auth.router). NULL means password-only —
    # Google sign-in for this email must prove password ownership first,
    # rather than being silently matched by email alone.
    google_linked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    manager: Mapped["User | None"] = relationship(remote_side=[id])
    access_level = relationship("AccessLevel", lazy="joined")
    profile: Mapped["MemberProfile | None"] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )

    @property
    def google_linked(self) -> bool:
        return self.google_linked_at is not None


class MemberProfile(Base):
    """A member on the org's roster — the record the member database is made
    of (MTR ID, contact and biographical fields, event participations, dues).

    The roster is its own entity: a member may or may not have a portal
    account. `user_id` links the two when they do (anyone with a Gmail on the
    roster gets one, and signs in with Google); members without a Gmail stay
    roster-only until one is added. `full_name` / `email` are the roster's own
    copy, so roster views show the member database's name; the account's own
    name stays the public display name (Hall of Fame).
    Every field is optional: the source data is patchy."""

    __tablename__ = "member_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), unique=True, index=True, nullable=True
    )
    mtr_id: Mapped[str | None] = mapped_column(String(20), unique=True, index=True, nullable=True)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)
    national_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    birthday: Mapped[date | None] = mapped_column(Date, nullable=True)
    university: Mapped[str | None] = mapped_column(String(255), nullable=True)
    college: Mapped[str | None] = mapped_column(String(255), nullable=True)
    major: Mapped[str | None] = mapped_column(String(255), nullable=True)
    graduating_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # One or more guardian phone numbers, stored comma-separated in a single
    # column so the flat-text consumers (bulk editor, roster import) keep
    # treating it as an ordinary text cell.
    guardian_phone: Mapped[str | None] = mapped_column(String(255), nullable=True)
    guardian_kinship: Mapped[str | None] = mapped_column(String(50), nullable=True)
    uni_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # The member's governorate / home city (the roster's "Governorate").
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # First registration with the team — drives dues maturity (years with MTR).
    joined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # How sure the roster is that this row is one real person: "high" (several
    # source records agree), "single" (one record), "review" (merged on weak
    # keys or sharing an ID with someone else — see review_note).
    data_confidence: Mapped[str | None] = mapped_column(String(20), nullable=True)
    source_records: Mapped[int | None] = mapped_column(Integer, nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    user: Mapped["User | None"] = relationship(back_populates="profile")

    @property
    def display_name(self) -> str:
        """The roster's name for the member (the member database is the source
        of truth), falling back to the account's name. Public surfaces like the
        Hall of Fame keep using the account's name."""
        if self.full_name:
            return self.full_name
        if self.user is not None:
            return self.user.full_name
        return self.email or self.mtr_id or f"Member #{self.id}"
