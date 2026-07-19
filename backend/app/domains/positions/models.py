from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Position(Base):
    """A node in the org chart: a title with a parent and zero or more
    occupants (see PositionOccupant) — a vacant seat still exists in the tree,
    and nothing stops a seat from having more than one occupant (co-leads,
    a whole team roster, etc).

    role_template_id/entity_type/entity_id mark a position as managed by a
    RoleTemplate (see app/domains/positions/role_engine.py) rather than a
    real, permanently-held org seat — all NULL for every ordinary position.
    These positions are never someone's sole "real seat" (see
    clear_user_from_other_positions) and never set anyone's manager_id (see
    resync_managers) — they're an extra "hat", not a place in the hierarchy."""

    __tablename__ = "positions"
    __table_args__ = (UniqueConstraint("role_template_id", "entity_type", "entity_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("positions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    is_technical: Mapped[bool] = mapped_column(Boolean, default=False)
    # The power this seat confers on its occupants (see app/domains/access).
    # NULL — the default — confers nothing: creating org structure never
    # accidentally hands out privileges.
    access_level_id: Mapped[int | None] = mapped_column(
        ForeignKey("access_levels.id", ondelete="SET NULL"), nullable=True
    )
    role_template_id: Mapped[int | None] = mapped_column(
        ForeignKey("role_templates.id", ondelete="SET NULL"), nullable=True, index=True
    )
    entity_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    parent: Mapped["Position | None"] = relationship(remote_side=[id])
    role_template: Mapped["RoleTemplate | None"] = relationship()
    access_level = relationship("AccessLevel", lazy="joined")
    occupant_links: Mapped[list["PositionOccupant"]] = relationship(
        back_populates="position", cascade="all, delete-orphan",
        order_by="PositionOccupant.id", lazy="selectin",
    )
    occupants = relationship(
        "User", secondary="position_occupants", viewonly=True,
        order_by="PositionOccupant.id", lazy="selectin",
    )


class PositionOccupant(Base):
    """One person filling one seat. A position can have zero, one, or many —
    a real job usually has one in practice, but nothing enforces that; a role
    meant for a whole roster (e.g. Team Member) naturally has many."""

    __tablename__ = "position_occupants"
    __table_args__ = (UniqueConstraint("position_id", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    position_id: Mapped[int] = mapped_column(
        ForeignKey("positions.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    position: Mapped[Position] = relationship(back_populates="occupant_links")
    user = relationship("User", foreign_keys=[user_id], lazy="joined")


class RoleTemplate(Base):
    """An admin-defined role, e.g. "{competition} PM" or "{member}" — fully
    data-driven, no role name is ever hardcoded in Python. `event` is one of
    the three fixed points in the app that can seat someone (creating a
    competition, creating a team, adding a team member) — that's the app's
    fixed structure, not a hardcoded role. `sort_order` is globally unique
    across every template and defines the single chain: this template's
    positions are parented under whichever earlier-in-order template already
    has a position for an ancestor entity (competition -> team ->
    membership), or under RoleChainRoot if none does yet.

    access_level_id: the power every position this template produces confers
    on its occupants — same meaning as Position.access_level_id, copied onto
    each produced position at creation time. This is what replaced the old
    grants_management flag: a "{competition} PM" template set to a level
    whose privileges include competitions.manage_seated makes its occupants
    managers of that competition; a "{member}" template with no level (or a
    powerless one) is just an org-chart seat. NULL confers nothing.

    Every seat starts vacant — nothing auto-seats a creator — except
    event="team_member_added", where the added member *is* the seat's
    meaning and always occupies it.

    Chaining: this template's positions parent under whichever earlier
    (lower sort_order) template already has a position for an ancestor
    entity, or under RoleChainRoot if no earlier template applies at all. If
    an earlier template *does* apply (its event's entity type is part of
    this entity's lineage) but hasn't produced a position for it yet, this
    template is skipped entirely rather than falling back to root — see
    role_engine._find_chain_parent. That's what makes a role "non-chaining"
    in practice: give it a sort_order with nothing eligible before it in its
    own lineage, and it always resolves straight to root."""

    __tablename__ = "role_templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    title_template: Mapped[str] = mapped_column(String(255))
    event: Mapped[str] = mapped_column(String(30), index=True)
    sort_order: Mapped[int] = mapped_column(Integer, unique=True)
    access_level_id: Mapped[int | None] = mapped_column(
        ForeignKey("access_levels.id", ondelete="SET NULL"), nullable=True
    )

    access_level = relationship("AccessLevel", lazy="joined")


class RoleChainRoot(Base):
    """Singleton (id=1): the org-chart parent for the very first role-template
    position ever placed, asked once, ever — every later template chains
    under an earlier template's own resulting position instead."""

    __tablename__ = "role_chain_root"

    id: Mapped[int] = mapped_column(primary_key=True)
    position_id: Mapped[int | None] = mapped_column(
        ForeignKey("positions.id", ondelete="SET NULL"), nullable=True
    )


class OrgAuditLog(Base):
    """Append-only record of every structural change to the org tree."""

    __tablename__ = "org_audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    action: Mapped[str] = mapped_column(String(40))  # create|rename|reparent|assign|vacate|delete|technical
    position_id: Mapped[int | None] = mapped_column(nullable=True)  # may be gone after delete
    detail: Mapped[str] = mapped_column(Text, default="")  # JSON: before/after
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )
