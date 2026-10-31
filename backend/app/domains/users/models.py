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
    """A person — member and account in one. Every member of the org has a
    row here, whether or not they have ever signed in: the roster fields
    (MTR ID, contact, university, …) live on the same row as the login, so
    there is exactly one id per person and one person picker everywhere.

    A row nobody has signed into yet is *unclaimed*: no usable password and
    no Google link (see `claimed`). Its owner claims it by signing in with
    Google, registering, or a password-reset mail to its email; members
    without an email simply can't sign in until one is added.

    What a person can *do* is decided entirely by the access ladder (see
    app/domains/access): their effective level is the union of the org seats
    they occupy plus the personal override below — there is no role list and
    no hardcoded job name anywhere. `manager_id` remains the structural
    reporting line (task subtree, visibility)."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    # NULL for members the roster has no email for — they can't sign in yet.
    email: Mapped[str | None] = mapped_column(String(255), unique=True, index=True, nullable=True)
    full_name: Mapped[str] = mapped_column(String(255))
    # UNUSABLE_PASSWORD (app.core.security) until the owner sets one.
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

    # --- roster fields (the member database). Every one optional: the source
    # data is patchy, and accounts like the bootstrap admin have none.
    mtr_id: Mapped[str | None] = mapped_column(String(20), unique=True, index=True, nullable=True)
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

    manager: Mapped["User | None"] = relationship(remote_side=[id])
    access_level = relationship("AccessLevel", lazy="joined")

    @property
    def google_linked(self) -> bool:
        return self.google_linked_at is not None

    @property
    def claimed(self) -> bool:
        """Has the owner ever been able to sign in (a password of their own or
        a linked Google identity)? False for members added by an admin or the
        roster import who haven't been invited yet."""
        from app.core.security import UNUSABLE_PASSWORD

        return self.google_linked_at is not None or self.hashed_password != UNUSABLE_PASSWORD

    @property
    def label(self) -> str:
        """How a person reads in any picker: MTR ID first when they have one."""
        return f"{self.mtr_id} — {self.full_name}" if self.mtr_id else self.full_name
