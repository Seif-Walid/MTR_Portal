from datetime import date, datetime, timezone
from enum import StrEnum

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class CompetitionStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class EventKind(Base):
    """A kind of event — Competition, Training, R&D, or any the admin adds.
    Every kind shares the exact same structure (a top entity -> categories ->
    teams -> members, all stored in the competitions tables); a kind only
    changes the *labels* shown for each level and namespaces automatic roles.
    So a "Training" is a Competition row whose kind labels its top level
    "Training Season", its teams "Group", etc. Fully data-driven — no event
    kind is hardcoded in Python (Competition/Training/R&D just ship as the
    starting rows)."""

    __tablename__ = "event_kinds"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(50), unique=True)  # stable id for routing
    name: Mapped[str] = mapped_column(String(100))  # the tab / kind name, e.g. "Training"
    # what one level is called for this kind — the "different names" per kind
    event_label: Mapped[str] = mapped_column(String(100), default="Event")  # e.g. "Training Season"
    category_label: Mapped[str] = mapped_column(String(100), default="Category")
    team_label: Mapped[str] = mapped_column(String(100), default="Team")  # e.g. "Group"
    member_label: Mapped[str] = mapped_column(String(100), default="Member")
    sort_order: Mapped[int] = mapped_column(Integer, unique=True)


class Competition(Base):
    """An event: name, dates, a kind (see EventKind), and a tree of categories
    -> teams -> members. Historically called "Competition" — it is now the
    generic event entity, its display identity (Competition vs Training vs
    R&D vs …) coming from `kind`. Who manages it is entirely a matter of who
    occupies the role-template positions the admin configured for its kind
    (see app/domains/positions/role_engine.py)."""

    __tablename__ = "competitions"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    kind_id: Mapped[int | None] = mapped_column(
        ForeignKey("event_kinds.id", ondelete="SET NULL"), nullable=True, index=True
    )
    description: Mapped[str] = mapped_column(Text, default="")
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default=CompetitionStatus.ACTIVE, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    kind: Mapped["EventKind | None"] = relationship(lazy="joined")
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
