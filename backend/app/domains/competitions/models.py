from datetime import date, datetime, timezone
from enum import StrEnum

from sqlalchemy import Date, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class CompetitionStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class Competition(Base):
    """A competition: name, dates, one or more Project Managers, and a tree of
    categories → teams → members. Roles here are scoped to this competition."""

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

    pms: Mapped[list["CompetitionPM"]] = relationship(
        back_populates="competition", cascade="all, delete-orphan", lazy="selectin"
    )
    categories: Mapped[list["CompetitionCategory"]] = relationship(
        back_populates="competition", cascade="all, delete-orphan", lazy="selectin"
    )


class CompetitionPM(Base):
    """A Project Manager responsible for a whole competition."""

    __tablename__ = "competition_pms"
    __table_args__ = (UniqueConstraint("competition_id", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    competition_id: Mapped[int] = mapped_column(
        ForeignKey("competitions.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)

    competition: Mapped[Competition] = relationship(back_populates="pms")
    user = relationship("User", foreign_keys=[user_id], lazy="joined")


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
    """A team within a category. A team has one lead and its own members."""

    __tablename__ = "competition_teams"

    id: Mapped[int] = mapped_column(primary_key=True)
    category_id: Mapped[int] = mapped_column(
        ForeignKey("competition_categories.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    lead_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )

    category: Mapped[CompetitionCategory] = relationship(back_populates="teams")
    lead = relationship("User", foreign_keys=[lead_id], lazy="joined")
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
