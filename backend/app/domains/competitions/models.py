from datetime import date, datetime, timezone
from enum import StrEnum

from sqlalchemy import Date, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class CompetitionStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class CompetitionCategory(Base):
    """A managed division/class a competition belongs to (e.g. Senior, Junior)."""

    __tablename__ = "competition_categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class Competition(Base):
    """A competition with one team: a name, category, dates, a team name, a
    team lead, and members."""

    __tablename__ = "competitions"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("competition_categories.id", ondelete="SET NULL"), nullable=True, index=True
    )
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default=CompetitionStatus.ACTIVE, index=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    # the team
    team_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    team_lead_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    category = relationship("CompetitionCategory", lazy="joined")
    team_lead = relationship("User", foreign_keys=[team_lead_id], lazy="joined")
    members: Mapped[list["CompetitionMember"]] = relationship(
        back_populates="competition", cascade="all, delete-orphan", lazy="selectin"
    )


class CompetitionMember(Base):
    __tablename__ = "competition_members"
    __table_args__ = (UniqueConstraint("competition_id", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    competition_id: Mapped[int] = mapped_column(
        ForeignKey("competitions.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)

    competition: Mapped[Competition] = relationship(back_populates="members")
    user = relationship("User", foreign_keys=[user_id], lazy="joined")
