from datetime import date, datetime, timezone
from enum import StrEnum

from sqlalchemy import Date, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class CompetitionStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class Competition(Base):
    """A competition: name, dates, and a tree of categories -> teams ->
    members. Who manages it (PM or equivalent) is entirely a matter of who
    occupies whatever role-template positions the admin has configured for
    it (see app/domains/positions/role_engine.py) — there is no dedicated
    "PM" concept in this model."""

    __tablename__ = "competitions"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default=CompetitionStatus.ACTIVE, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    categories: Mapped[list["CompetitionCategory"]] = relationship(
        back_populates="competition", cascade="all, delete-orphan", lazy="selectin"
    )


class CompetitionCategory(Base):
    """A division within a competition (e.g. Senior, Junior). Categories hold teams."""

    __tablename__ = "competition_categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    competition_id: Mapped[int] = mapped_column(
        ForeignKey("competitions.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))

    competition: Mapped[Competition] = relationship(back_populates="categories")
    teams: Mapped[list["CompetitionTeam"]] = relationship(
        back_populates="category", cascade="all, delete-orphan", lazy="selectin"
    )


class CompetitionTeam(Base):
    """A team within a category. Who leads/coaches it is, like a competition's
    PM, entirely a matter of role-position occupancy — no dedicated fields
    here for that."""

    __tablename__ = "competition_teams"

    id: Mapped[int] = mapped_column(primary_key=True)
    category_id: Mapped[int] = mapped_column(
        ForeignKey("competition_categories.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    # Soft delete: a team is historical context (who competed, allocation
    # linkage, task history) — removing the row would lose that. A genuine
    # hard delete is a separate admin-only escape hatch.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    category: Mapped[CompetitionCategory] = relationship(back_populates="teams")
    members: Mapped[list["CompetitionTeamMember"]] = relationship(
        back_populates="team", cascade="all, delete-orphan", lazy="selectin"
    )


class CompetitionTeamMember(Base):
    __tablename__ = "competition_team_members"
    __table_args__ = (UniqueConstraint("team_id", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    team_id: Mapped[int] = mapped_column(
        ForeignKey("competition_teams.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)

    team: Mapped[CompetitionTeam] = relationship(back_populates="members")
    user = relationship("User", foreign_keys=[user_id], lazy="joined")
