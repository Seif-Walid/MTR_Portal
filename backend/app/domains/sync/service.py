"""Live two-way DB<->Sheets mirror. The database is the source of truth; each
mirrored tab in the spreadsheet is kept in step with it.

Scope: the mirror covers structural/reference data — people, org positions,
events (+ categories/teams/members), and inventory (items/locations/
movements). Operational workflow state (tasks, work requests, notifications,
sessions, audit logs) is out of scope. See DECISIONS.md.

Reconcile is symmetric: edit/add/delete in the sheet OR in the app and both
sides converge. The heavy lifting of validating and applying sheet rows lives
in bulk.service; this module drives the per-tab read -> pull -> push -> snapshot
loop and tracks the id set that lets a sheet-side delete be told apart from an
app-side insert.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import gsheets
from app.domains.events.models import (
    Event,
    EventCategory,
    EventKind,
    EventTeam,
    EventTeamMember,
)
from app.domains.inventory.models import InventoryItem, Location, StockMovement
from app.domains.positions.models import Position
from app.domains.sync.models import SheetExport
from app.domains.users.models import User

MIRROR_BANNER = (
    "[ MIRROR — EDITS HERE ARE NOT READ BACK. Rebuild from Sheets to make this authoritative. ]"
)

# Dependency order: each tab may only reference ids from tabs earlier in this
# list (plus itself, for the self-referential manager_id / parent_id cases).
TAB_ORDER = [
    "people",
    "positions",
    "event_kinds",
    "events",
    "event_categories",
    "event_teams",
    "event_team_members",
    "inventory_locations",
    "inventory_items",
    "inventory_movements",
]


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


# --- export: DB row -> sheet row -------------------------------------------
def _export_people(db: Session) -> tuple[list[str], list[list[str]]]:
    header = ["id", "email", "full_name", "department", "access_level", "manager_id", "is_active"]
    rows = []
    # Deactivated users are the People table's soft-delete: they keep their row
    # for FK integrity (manager_id, movement actor, ...) but drop out of the
    # live mirror, so deleting a person in the grid/sheet actually makes them
    # disappear from both sides — same contract as the deleted_at filters below.
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


def _export_events(db: Session) -> tuple[list[str], list[list[str]]]:
    header = ["id", "name", "kind", "description", "start_date", "end_date", "status"]
    rows = [
        [_s(c.id), c.name, c.kind.slug if c.kind else "", c.description, _s(c.start_date), _s(c.end_date), c.status]
        for c in db.scalars(select(Event).order_by(Event.id))
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
    header = ["id", "category_id", "name"]
    rows = [
        [_s(t.id), _s(t.category_id), t.name]
        for t in db.scalars(
            select(EventTeam).where(EventTeam.deleted_at.is_(None)).order_by(EventTeam.id)
        )
    ]
    return header, rows


def _export_team_members(db: Session) -> tuple[list[str], list[list[str]]]:
    header = ["id", "team_id", "user_id"]
    rows = [
        [_s(m.id), _s(m.team_id), _s(m.user_id)]
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
    "events": _export_events,
    "event_categories": _export_categories,
    "event_teams": _export_teams,
    "event_team_members": _export_team_members,
    "inventory_locations": _export_locations,
    "inventory_items": _export_items,
    "inventory_movements": _export_movements,
}


def _get_or_create_tracking(db: Session, tab: str) -> SheetExport:
    row = db.scalar(select(SheetExport).where(SheetExport.tab == tab))
    if row is None:
        row = SheetExport(tab=tab, is_dirty=True)
        db.add(row)
        db.flush()
    return row


def mark_dirty(db: Session, tab: str) -> None:
    """Call after any change to a mirrored entity so its tab shows as stale
    until the next push. No async queue in this stack (see DECISIONS.md) — this
    just flips a flag."""
    _get_or_create_tracking(db, tab).is_dirty = True


def export_tab(db: Session, spreadsheet_id: str, tab: str) -> int:
    header, rows = _EXPORTERS[tab](db)
    tracking = _get_or_create_tracking(db, tab)
    try:
        gsheets.write_worksheet(spreadsheet_id, tab, header, rows, banner=MIRROR_BANNER)
    except Exception as exc:  # noqa: BLE001 — record it, never crash the request
        tracking.last_error = str(exc)
        db.commit()
        raise
    tracking.row_count = len(rows)
    tracking.is_dirty = False
    tracking.last_error = ""
    tracking.last_synced_at = datetime.now(timezone.utc)
    db.commit()
    return len(rows)


# --- live two-way reconcile -------------------------------------------------
# The mirror is symmetric: edit/add/delete in the sheet OR in the app, and both
# sides converge. One reconcile of a tab does, in order:
#   1. read the sheet;
#   2. pull it into the DB — inserts (blank id), updates, and the deletes that
#      the sheet-side removed (ids that were present at the last sync but are
#      now gone from the sheet);
#   3. push the resulting DB state back over the tab, so app-side inserts,
#      edits and deletes appear in the sheet too;
#   4. snapshot the id set now in the tab, for the next diff.
# Because the pull happens before the push, a row still being typed in the sheet
# is captured into the DB first and then written back — the full rewrite never
# eats an in-flight edit. A row created in the app (its id absent from the
# previous snapshot) is pushed, never mistaken for a sheet-side deletion.
def _visible_ids(db: Session, tab: str) -> set[int]:
    """The ids the exporter actually emits for a tab (i.e. what is really in the
    sheet after a push) — soft-deleted / deactivated rows are already filtered
    out by the exporters, so this is the authoritative 'present in the mirror'
    set."""
    _, rows = _EXPORTERS[tab](db)
    return {int(r[0]) for r in rows if r and str(r[0]).strip()}


def reconcile_tab(
    db: Session, spreadsheet_id: str, tab: str, actor_id: int | None = None
) -> dict:
    # Imported lazily: bulk.service imports this module, so a top-level import
    # would be circular.
    from app.domains.bulk import service as bulk
    from app.domains.bulk.registry import TABLES

    spec = TABLES.get(tab)
    if spec is None:
        return {"tab": tab, "ok": False, "error": f"unknown tab '{tab}'"}
    tracking = _get_or_create_tracking(db, tab)
    prev_ids = set(json.loads(tracking.synced_ids or "[]"))

    try:
        header, sheet_rows = gsheets.read_worksheet(spreadsheet_id, tab)
    except Exception as exc:  # noqa: BLE001 — record, keep syncing the other tabs
        tracking.last_error = f"read failed: {exc}"
        db.commit()
        return {"tab": tab, "ok": False, "error": str(exc)}

    expected = [c.name for c in spec.columns]
    if any(c not in header for c in expected):
        # tab missing / columns dropped — (re)initialise it from the DB rather
        # than trusting a malformed sheet.
        export_tab(db, spreadsheet_id, tab)
        _snapshot(db, tab)
        return {"tab": tab, "ok": True, "repaired": True, "adds": 0, "updates": 0, "deletes": 0}

    rows = [{name: r.get(name, "") for name in expected} for r in sheet_rows]

    # Validate first: if the sheet has bad data, do NOT push over it (that would
    # eat whatever the user is fixing) — surface the error and leave it be.
    coerced, errors, _ = bulk.validate(db, spec, rows, [])
    if errors:
        tracking.last_error = "; ".join(e["message"] for e in errors[:5])
        db.commit()
        return {"tab": tab, "ok": False, "errors": errors}

    sheet_ids = {c.id for c in coerced if c.id is not None}
    can_delete = not (spec.append_only or spec.delete == "none")
    existing = {r[0] for r in db.execute(select(spec.model.id)).all()}
    # deleted in the sheet = was in the mirror last time, still in the DB, gone
    # from the sheet now.
    deletes = sorted((prev_ids - sheet_ids) & existing) if can_delete else []

    result = bulk.apply(db, spec, rows, deletes, actor_id)
    if not result["ok"]:
        tracking.last_error = "; ".join(e["message"] for e in result["errors"][:5])
        db.commit()
        return {"tab": tab, "ok": False, "errors": result["errors"]}

    # push DB -> sheet (reflects app-side adds/edits/deletes), then snapshot.
    export_tab(db, spreadsheet_id, tab)
    _snapshot(db, tab)
    return {"tab": tab, "ok": True, **result["summary"]}


def _snapshot(db: Session, tab: str) -> None:
    """Record the tab's current mirror id set and clear its error, after a push."""
    tracking = _get_or_create_tracking(db, tab)  # re-fetch: export_tab committed
    tracking.synced_ids = json.dumps(sorted(_visible_ids(db, tab)))
    tracking.last_error = ""
    db.commit()


def reconcile_all(db: Session, spreadsheet_id: str, actor_id: int | None = None) -> dict:
    """Reconcile every tab in dependency order (people before the things that
    reference them). Called on a timer by the sheet's Apps Script."""
    return {tab: reconcile_tab(db, spreadsheet_id, tab, actor_id) for tab in TAB_ORDER}
