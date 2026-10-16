"""Row serialization for the bulk-editor grid and its Excel export: one
exporter per curated table turning DB rows into (header, rows) of string cells.
Header order matches the table's columns in registry.py exactly."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domains.events.models import (
    EventCategory,
    EventKind,
    EventTeam,
    EventTeamMember,
)
from app.domains.inventory.models import InventoryItem, Location, StockMovement
from app.domains.positions.models import Position
from app.domains.users.models import User


def _s(v) -> str:
    return "" if v is None else str(v)


def _bool(v: str) -> bool:
    return v.strip().lower() in ("true", "1", "yes")


def _parse_date(v: str) -> date | None:
    v = v.strip()
    return date.fromisoformat(v) if v else None


def _parse_datetime(v: str) -> datetime | None:
    v = v.strip()
    return datetime.fromisoformat(v) if v else None


# --- export: DB row -> grid row ---------------------------------------------
def _export_people(db: Session) -> tuple[list[str], list[list[str]]]:
    header = ["id", "email", "full_name", "department", "access_level", "manager_id", "is_active"]
    rows = []
    # Deactivated users are the People table's soft-delete: they keep their row
    # for FK integrity (manager_id, movement actor, ...) but drop out of the
    # grid, so deleting a person actually makes them disappear — same contract
    # as the deleted_at filters below.
    for u in db.scalars(select(User).where(User.is_active.is_(True)).order_by(User.id)):
        rows.append([
            _s(u.id), u.email, u.full_name, _s(u.department),
            u.access_level.name if u.access_level else "", _s(u.manager_id), _s(u.is_active),
        ])
    return header, rows


def _export_positions(db: Session) -> tuple[list[str], list[list[str]]]:
    header = ["id", "title", "parent_id", "occupant_ids", "is_technical", "access_level"]
    rows = [
        [_s(p.id), p.title, _s(p.parent_id), ";".join(str(u.id) for u in p.occupants), _s(p.is_technical),
         p.access_level.name if p.access_level else ""]
        for p in db.scalars(select(Position).order_by(Position.id))
    ]
    return header, rows


def _export_event_kinds(db: Session) -> tuple[list[str], list[list[str]]]:
    header = ["id", "slug", "name", "event_label", "category_label", "team_label", "member_label", "sort_order"]
    rows = [
        [_s(k.id), k.slug, k.name, k.event_label, k.category_label, k.team_label, k.member_label, _s(k.sort_order)]
        for k in db.scalars(select(EventKind).order_by(EventKind.sort_order))
    ]
    return header, rows


def _export_categories(db: Session) -> tuple[list[str], list[list[str]]]:
    header = ["id", "event_id", "name"]
    rows = [
        [_s(c.id), _s(c.event_id), c.name]
        for c in db.scalars(select(EventCategory).order_by(EventCategory.id))
    ]
    return header, rows


def _export_teams(db: Session) -> tuple[list[str], list[list[str]]]:
    header = ["id", "category_id", "name", "award"]
    rows = [
        [_s(t.id), _s(t.category_id), t.name, t.award or ""]
        for t in db.scalars(
            select(EventTeam).where(EventTeam.deleted_at.is_(None)).order_by(EventTeam.id)
        )
    ]
    return header, rows


def _export_team_members(db: Session) -> tuple[list[str], list[list[str]]]:
    header = ["id", "team_id", "user_id", "role"]
    rows = [
        [_s(m.id), _s(m.team_id), _s(m.user_id), m.role or ""]
        for m in db.scalars(select(EventTeamMember).order_by(EventTeamMember.id))
    ]
    return header, rows


def _export_locations(db: Session) -> tuple[list[str], list[list[str]]]:
    header = ["id", "name", "kind", "notes"]
    rows = [
        [_s(l.id), l.name, l.kind, l.notes]
        for l in db.scalars(select(Location).order_by(Location.id))
    ]
    return header, rows


def _export_items(db: Session) -> tuple[list[str], list[list[str]]]:
    header = ["id", "name", "category", "asset_tag", "sku", "quantity", "low_stock_threshold",
              "unit", "location", "condition", "notes", "team_lead_id"]
    rows = [
        [_s(i.id), i.name, _s(i.category), _s(i.asset_tag), _s(i.sku), _s(i.quantity),
         _s(i.low_stock_threshold), i.unit, _s(i.location), i.condition, i.notes, _s(i.team_lead_id)]
        for i in db.scalars(
            select(InventoryItem).where(InventoryItem.deleted_at.is_(None)).order_by(InventoryItem.id)
        )
    ]
    return header, rows


def _export_movements(db: Session) -> tuple[list[str], list[list[str]]]:
    header = ["id", "item_id", "quantity", "from_location_id", "from_holder_id",
              "to_location_id", "to_holder_id", "actor_id", "reason", "created_at"]
    rows = [
        [_s(m.id), _s(m.item_id), _s(m.quantity), _s(m.from_location_id), _s(m.from_holder_id),
         _s(m.to_location_id), _s(m.to_holder_id), _s(m.actor_id), m.reason, _s(m.created_at)]
        for m in db.scalars(select(StockMovement).order_by(StockMovement.id))
    ]
    return header, rows


_EXPORTERS = {
    "people": _export_people,
    "positions": _export_positions,
    "event_kinds": _export_event_kinds,
    "event_categories": _export_categories,
    "event_teams": _export_teams,
    "event_team_members": _export_team_members,
    "inventory_locations": _export_locations,
    "inventory_items": _export_items,
    "inventory_movements": _export_movements,
}
