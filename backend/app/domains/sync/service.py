"""Rebuild-from-Sheets: the database is the source of truth; Sheets is a
mirror. Outbound export pushes the current DB into per-entity tabs. Inbound
rebuild is the opposite and destructive direction — it takes the Sheets as
truth and replaces the DB wholesale. It never merges or reconciles.

Scope: the mirror covers structural/reference data — people, org positions,
competitions (+ categories/teams/members), and inventory (items/locations/
movements). Operational workflow state (tasks, work requests, notifications,
sessions, the audit logs, and checkout requests) is out of scope — a
spreadsheet snapshot can't meaningfully replace in-flight process state — but
since that state references people/items/competitions by foreign key, a
rebuild must still clear or de-reference it so the DB never ends up with
dangling references. See DECISIONS.md.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.core import gsheets
from app.core.config import settings
from app.core.security import hash_password
from app.domains.auth.models import AuthSession
from app.domains.competitions.models import (
    Competition,
    CompetitionCategory,
    CompetitionStatus,
    CompetitionTeam,
    CompetitionTeamMember,
)
from app.domains.inventory.models import (
    Condition,
    InventoryAllocation,
    InventoryItem,
    InventoryRequest,
    Location,
    LocationKind,
    StockMovement,
)
from app.domains.notifications.models import Notification
from app.domains.positions.models import OrgAuditLog, Position, PositionOccupant
from app.domains.requests.models import WorkRequest
from app.domains.sync.models import RebuildBatch, RebuildStatus, SheetExport
from app.domains.tasks.models import Task, TaskAttachment
from app.domains.access.models import AccessLevel
from app.domains.users.models import User
from app.domains.audit.models import AuditLog as GeneralAuditLog

MIRROR_BANNER = (
    "[ MIRROR — EDITS HERE ARE NOT READ BACK. Rebuild from Sheets to make this authoritative. ]"
)

# Dependency order: each tab may only reference ids from tabs earlier in this
# list (plus itself, for the self-referential manager_id / parent_id cases).
TAB_ORDER = [
    "people",
    "positions",
    "competitions",
    "competition_categories",
    "competition_teams",
    "competition_team_members",
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


def _parse_int(v: str) -> int | None:
    v = v.strip()
    return int(v) if v else None


# --- export: DB row -> sheet row -------------------------------------------
def _export_people(db: Session) -> tuple[list[str], list[list[str]]]:
    header = ["id", "email", "full_name", "department", "access_level", "manager_id", "is_active"]
    rows = []
    for u in db.scalars(select(User).order_by(User.id)):
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


def _export_competitions(db: Session) -> tuple[list[str], list[list[str]]]:
    header = ["id", "name", "description", "start_date", "end_date", "status"]
    rows = [
        [_s(c.id), c.name, c.description, _s(c.start_date), _s(c.end_date), c.status]
        for c in db.scalars(select(Competition).order_by(Competition.id))
    ]
    return header, rows


def _export_categories(db: Session) -> tuple[list[str], list[list[str]]]:
    header = ["id", "competition_id", "name"]
    rows = [
        [_s(c.id), _s(c.competition_id), c.name]
        for c in db.scalars(select(CompetitionCategory).order_by(CompetitionCategory.id))
    ]
    return header, rows


def _export_teams(db: Session) -> tuple[list[str], list[list[str]]]:
    header = ["id", "category_id", "name"]
    rows = [
        [_s(t.id), _s(t.category_id), t.name]
        for t in db.scalars(
            select(CompetitionTeam).where(CompetitionTeam.deleted_at.is_(None)).order_by(CompetitionTeam.id)
        )
    ]
    return header, rows


def _export_team_members(db: Session) -> tuple[list[str], list[list[str]]]:
    header = ["id", "team_id", "user_id"]
    rows = [
        [_s(m.id), _s(m.team_id), _s(m.user_id)]
        for m in db.scalars(select(CompetitionTeamMember).order_by(CompetitionTeamMember.id))
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
    "competitions": _export_competitions,
    "competition_categories": _export_categories,
    "competition_teams": _export_teams,
    "competition_team_members": _export_team_members,
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
    """Call after any change to a mirrored entity so the admin UI shows the
    tab as stale until the next export. No async queue in this stack (see
    DECISIONS.md) — this just flips a flag; export itself is manually
    triggered."""
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


def export_all(db: Session, spreadsheet_id: str) -> dict[str, int]:
    counts = {}
    for tab in TAB_ORDER:
        counts[tab] = export_tab(db, spreadsheet_id, tab)
    return counts


def list_exports(db: Session) -> list[SheetExport]:
    existing = {r.tab: r for r in db.scalars(select(SheetExport))}
    for tab in TAB_ORDER:
        if tab not in existing:
            existing[tab] = _get_or_create_tracking(db, tab)
    db.commit()
    return [existing[t] for t in TAB_ORDER]


# --- import: sheet rows -> validated field dicts ----------------------------
def _require(row: dict[str, str], *keys: str, tab: str, errors: list[str]) -> bool:
    missing = [k for k in keys if not row.get(k, "").strip()]
    if missing:
        errors.append(f"{tab} row {row.get('id', '?')}: missing {', '.join(missing)}")
        return False
    return True


def _check_ref(value: str, known: set[int], tab: str, row_id: str, field: str, errors: list[str]) -> int | None:
    if not value.strip():
        return None
    ref = int(value)
    if ref not in known:
        errors.append(f"{tab} row {row_id}: {field}={ref} does not resolve")
        return None
    return ref


def _read_all_tabs(spreadsheet_id: str) -> dict[str, list[dict[str, str]]]:
    data = {}
    for tab in TAB_ORDER:
        _, rows = gsheets.read_worksheet(spreadsheet_id, tab)
        data[tab] = rows
    return data


def _validate(db: Session, sheet_data: dict[str, list[dict[str, str]]]) -> tuple[dict[str, list[dict]], dict[str, int], list[str]]:
    """Parse + cross-reference every tab in dependency order. Returns
    (parsed rows per tab, row counts, errors). Parsing continues past errors
    so the report is complete, but the caller must refuse to commit if
    errors is non-empty."""
    errors: list[str] = []
    counts: dict[str, int] = {}
    parsed: dict[str, list[dict]] = {}
    known_ids: dict[str, set[int]] = {t: set() for t in TAB_ORDER}
    valid_levels = {lvl.name for lvl in db.scalars(select(AccessLevel))}

    # people
    people = []
    for row in sheet_data.get("people", []):
        if not _require(row, "id", "email", "full_name", tab="people", errors=errors):
            continue
        rid = int(row["id"])
        level_name = (row.get("access_level") or "").strip()
        if level_name and level_name not in valid_levels:
            errors.append(f"people row {rid}: unknown access level '{level_name}'")
            continue
        known_ids["people"].add(rid)
        people.append({
            "id": rid, "email": row["email"].strip().lower(), "full_name": row["full_name"],
            "department": row.get("department") or None, "access_level": level_name,
            "manager_id_raw": row.get("manager_id", ""), "is_active": _bool(row.get("is_active", "true")),
        })
    parsed["people"] = people
    counts["people"] = len(people)

    # positions (self-referential parent_id; occupant_ids -> people, ";"-joined)
    positions = []
    for row in sheet_data.get("positions", []):
        if not _require(row, "id", "title", tab="positions", errors=errors):
            continue
        rid = int(row["id"])
        occ_ids = [
            _check_ref(v, known_ids["people"], "positions", row["id"], "occupant_ids", errors)
            for v in row.get("occupant_ids", "").split(";") if v.strip()
        ]
        known_ids["positions"].add(rid)
        level_name = (row.get("access_level") or "").strip()
        if level_name and level_name not in valid_levels:
            errors.append(f"positions row {rid}: unknown access level '{level_name}'")
            continue
        positions.append({
            "id": rid, "title": row["title"], "parent_id_raw": row.get("parent_id", ""),
            "occupant_ids": [o for o in occ_ids if o is not None],
            "is_technical": _bool(row.get("is_technical", "false")),
            "access_level": level_name,
        })
    for p in positions:  # parent refs its own tab, validate in a second pass
        if p["parent_id_raw"].strip():
            _check_ref(p["parent_id_raw"], known_ids["positions"], "positions", str(p["id"]), "parent_id", errors)
    parsed["positions"] = positions
    counts["positions"] = len(positions)

    # competitions
    competitions = []
    for row in sheet_data.get("competitions", []):
        if not _require(row, "id", "name", tab="competitions", errors=errors):
            continue
        rid = int(row["id"])
        status = row.get("status", "").strip() or CompetitionStatus.ACTIVE
        if status not in (CompetitionStatus.ACTIVE, CompetitionStatus.ARCHIVED):
            errors.append(f"competitions row {rid}: invalid status '{status}'")
            continue
        known_ids["competitions"].add(rid)
        competitions.append({
            "id": rid, "name": row["name"], "description": row.get("description", ""),
            "start_date": row.get("start_date", ""), "end_date": row.get("end_date", ""), "status": status,
        })
    parsed["competitions"] = competitions
    counts["competitions"] = len(competitions)

    # competition_categories
    categories = []
    for row in sheet_data.get("competition_categories", []):
        if not _require(row, "id", "competition_id", "name", tab="competition_categories", errors=errors):
            continue
        rid = int(row["id"])
        comp = _check_ref(row["competition_id"], known_ids["competitions"], "competition_categories", row["id"], "competition_id", errors)
        if comp is None:
            continue
        known_ids["competition_categories"].add(rid)
        categories.append({"id": rid, "competition_id": comp, "name": row["name"]})
    parsed["competition_categories"] = categories
    counts["competition_categories"] = len(categories)

    # competition_teams
    teams = []
    for row in sheet_data.get("competition_teams", []):
        if not _require(row, "id", "category_id", "name", tab="competition_teams", errors=errors):
            continue
        rid = int(row["id"])
        cat = _check_ref(row["category_id"], known_ids["competition_categories"], "competition_teams", row["id"], "category_id", errors)
        if cat is None:
            continue
        known_ids["competition_teams"].add(rid)
        teams.append({"id": rid, "category_id": cat, "name": row["name"]})
    parsed["competition_teams"] = teams
    counts["competition_teams"] = len(teams)

    # competition_team_members
    members = []
    for row in sheet_data.get("competition_team_members", []):
        if not _require(row, "id", "team_id", "user_id", tab="competition_team_members", errors=errors):
            continue
        rid = int(row["id"])
        team = _check_ref(row["team_id"], known_ids["competition_teams"], "competition_team_members", row["id"], "team_id", errors)
        usr = _check_ref(row["user_id"], known_ids["people"], "competition_team_members", row["id"], "user_id", errors)
        if team is None or usr is None:
            continue
        known_ids["competition_team_members"].add(rid)
        members.append({"id": rid, "team_id": team, "user_id": usr})
    parsed["competition_team_members"] = members
    counts["competition_team_members"] = len(members)

    # inventory_locations
    locations = []
    for row in sheet_data.get("inventory_locations", []):
        if not _require(row, "id", "name", tab="inventory_locations", errors=errors):
            continue
        rid = int(row["id"])
        kind = row.get("kind", "").strip() or LocationKind.OTHER
        known_ids["inventory_locations"].add(rid)
        locations.append({"id": rid, "name": row["name"], "kind": kind, "notes": row.get("notes", "")})
    parsed["inventory_locations"] = locations
    counts["inventory_locations"] = len(locations)

    # inventory_items
    items = []
    for row in sheet_data.get("inventory_items", []):
        if not _require(row, "id", "name", "quantity", tab="inventory_items", errors=errors):
            continue
        rid = int(row["id"])
        team_lead = _check_ref(row.get("team_lead_id", ""), known_ids["people"], "inventory_items", row["id"], "team_lead_id", errors)
        condition = row.get("condition", "").strip() or Condition.GOOD
        if condition not in {c.value for c in Condition}:
            errors.append(f"inventory_items row {rid}: invalid condition '{condition}'")
            continue
        known_ids["inventory_items"].add(rid)
        items.append({
            "id": rid, "name": row["name"], "category": row.get("category") or None,
            "asset_tag": row.get("asset_tag") or None, "sku": row.get("sku") or None,
            "quantity": int(row["quantity"]), "low_stock_threshold": _parse_int(row.get("low_stock_threshold", "")) or 0,
            "unit": row.get("unit") or "unit", "location": row.get("location") or None,
            "condition": condition, "notes": row.get("notes", ""), "team_lead_id": team_lead,
        })
    parsed["inventory_items"] = items
    counts["inventory_items"] = len(items)

    # inventory_movements
    movements = []
    for row in sheet_data.get("inventory_movements", []):
        if not _require(row, "id", "item_id", "quantity", tab="inventory_movements", errors=errors):
            continue
        rid = int(row["id"])
        item = _check_ref(row["item_id"], known_ids["inventory_items"], "inventory_movements", row["id"], "item_id", errors)
        if item is None:
            continue
        from_loc = _check_ref(row.get("from_location_id", ""), known_ids["inventory_locations"], "inventory_movements", row["id"], "from_location_id", errors)
        to_loc = _check_ref(row.get("to_location_id", ""), known_ids["inventory_locations"], "inventory_movements", row["id"], "to_location_id", errors)
        from_holder = _check_ref(row.get("from_holder_id", ""), known_ids["people"], "inventory_movements", row["id"], "from_holder_id", errors)
        to_holder = _check_ref(row.get("to_holder_id", ""), known_ids["people"], "inventory_movements", row["id"], "to_holder_id", errors)
        actor = _check_ref(row.get("actor_id", ""), known_ids["people"], "inventory_movements", row["id"], "actor_id", errors)
        known_ids["inventory_movements"].add(rid)
        movements.append({
            "id": rid, "item_id": item, "quantity": int(row["quantity"]),
            "from_location_id": from_loc, "from_holder_id": from_holder,
            "to_location_id": to_loc, "to_holder_id": to_holder, "actor_id": actor,
            "reason": row.get("reason", ""), "created_at_raw": row.get("created_at", ""),
        })
    parsed["inventory_movements"] = movements
    counts["inventory_movements"] = len(movements)

    return parsed, counts, errors


def dry_run(db: Session, spreadsheet_id: str) -> tuple[dict[str, int], list[str]]:
    """Read + validate every tab. Never writes to the DB (the session is
    only used to look up valid access-level names)."""
    sheet_data = _read_all_tabs(spreadsheet_id)
    _, counts, errors = _validate(db, sheet_data)
    return counts, errors


def _write_snapshot(db: Session) -> str:
    """A portable, DB-backend-agnostic pre-rebuild snapshot: every managed
    table's current rows, dumped to JSON. Written to storage before anything
    is touched."""
    settings.snapshot_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = settings.snapshot_dir / f"rebuild_{stamp}.json"

    def dump(model, cols):
        return [{c: _s(getattr(row, c)) for c in cols} for row in db.scalars(select(model))]

    snapshot = {
        "taken_at": stamp,
        "people": dump(User, ["id", "email", "full_name", "department", "manager_id", "is_active", "access_level_id"]),
        "positions": dump(Position, ["id", "title", "parent_id", "is_technical", "access_level_id"]),
        "position_occupants": dump(PositionOccupant, ["id", "position_id", "user_id"]),
        "competitions": dump(Competition, ["id", "name", "description", "start_date", "end_date", "status"]),
        "competition_categories": dump(CompetitionCategory, ["id", "competition_id", "name"]),
        "competition_teams": dump(CompetitionTeam, ["id", "category_id", "name", "deleted_at"]),
        "competition_team_members": dump(CompetitionTeamMember, ["id", "team_id", "user_id"]),
        "inventory_locations": dump(Location, ["id", "name", "kind", "notes"]),
        "inventory_items": dump(InventoryItem, ["id", "name", "quantity", "team_lead_id", "deleted_at"]),
        "inventory_movements": dump(StockMovement, ["id", "item_id", "quantity", "from_location_id",
                                                      "to_location_id", "from_holder_id", "to_holder_id"]),
    }
    path.write_text(json.dumps(snapshot, indent=2))
    return str(path)


def _clear_dependent_tables(db: Session) -> None:
    """Everything NOT in the mirror that references people/items/competitions
    by FK. De-reference self/mutual references first, then delete — order-
    independent regardless of whether FK enforcement is on."""
    db.execute(update(Task).values(origin_request_id=None))
    db.execute(update(WorkRequest).values(created_task_id=None))
    db.execute(delete(Notification))
    db.execute(delete(TaskAttachment))
    db.execute(delete(Task))
    db.execute(delete(WorkRequest))
    db.execute(delete(AuthSession))
    db.execute(delete(InventoryAllocation))
    db.execute(delete(InventoryRequest))
    db.execute(update(OrgAuditLog).values(actor_id=None))
    db.execute(update(GeneralAuditLog).values(actor_id=None))


def _truncate_managed_tables(db: Session) -> None:
    db.execute(delete(StockMovement))
    db.execute(delete(InventoryItem))
    db.execute(delete(Location))
    db.execute(delete(CompetitionTeamMember))
    db.execute(delete(CompetitionTeam))
    db.execute(delete(CompetitionCategory))
    db.execute(delete(Competition))
    db.execute(delete(PositionOccupant))
    db.execute(update(Position).values(parent_id=None))
    db.execute(delete(Position))
    db.execute(update(User).values(manager_id=None))
    db.execute(delete(User))


def _import_all(db: Session, parsed: dict[str, list[dict]]) -> None:
    levels_by_name = {lvl.name: lvl for lvl in db.scalars(select(AccessLevel))}

    for p in parsed["people"]:
        level = levels_by_name.get(p["access_level"]) if p.get("access_level") else None
        db.add(User(
            id=p["id"], email=p["email"], full_name=p["full_name"], department=p["department"],
            access_level_id=level.id if level else None,
            is_active=p["is_active"], hashed_password=hash_password("rebuild-" + str(p["id"]) + "-" +
                                                                       datetime.now(timezone.utc).isoformat()),
        ))
    db.flush()
    for p in parsed["people"]:  # second pass: self-referential manager_id
        if p["manager_id_raw"].strip():
            db.get(User, p["id"]).manager_id = int(p["manager_id_raw"])

    for pos in parsed["positions"]:
        level = levels_by_name.get(pos["access_level"]) if pos.get("access_level") else None
        db.add(Position(id=pos["id"], title=pos["title"], is_technical=pos["is_technical"],
                        access_level_id=level.id if level else None))
    db.flush()
    for pos in parsed["positions"]:
        if pos["parent_id_raw"].strip():
            db.get(Position, pos["id"]).parent_id = int(pos["parent_id_raw"])
        for uid in pos["occupant_ids"]:
            db.add(PositionOccupant(position_id=pos["id"], user_id=uid))

    for c in parsed["competitions"]:
        db.add(Competition(
            id=c["id"], name=c["name"], description=c["description"],
            start_date=_parse_date(c["start_date"]), end_date=_parse_date(c["end_date"]), status=c["status"],
        ))
    for cat in parsed["competition_categories"]:
        db.add(CompetitionCategory(id=cat["id"], competition_id=cat["competition_id"], name=cat["name"]))
    for t in parsed["competition_teams"]:
        db.add(CompetitionTeam(id=t["id"], category_id=t["category_id"], name=t["name"]))
    for m in parsed["competition_team_members"]:
        db.add(CompetitionTeamMember(id=m["id"], team_id=m["team_id"], user_id=m["user_id"]))
    for loc in parsed["inventory_locations"]:
        db.add(Location(id=loc["id"], name=loc["name"], kind=loc["kind"], notes=loc["notes"]))
    for it in parsed["inventory_items"]:
        db.add(InventoryItem(
            id=it["id"], name=it["name"], category=it["category"], asset_tag=it["asset_tag"], sku=it["sku"],
            quantity=it["quantity"], low_stock_threshold=it["low_stock_threshold"], unit=it["unit"],
            location=it["location"], condition=it["condition"], notes=it["notes"], team_lead_id=it["team_lead_id"],
        ))
    for mv in parsed["inventory_movements"]:
        db.add(StockMovement(
            id=mv["id"], item_id=mv["item_id"], quantity=mv["quantity"],
            from_location_id=mv["from_location_id"], from_holder_id=mv["from_holder_id"],
            to_location_id=mv["to_location_id"], to_holder_id=mv["to_holder_id"], actor_id=mv["actor_id"],
            reason=mv["reason"], created_at=_parse_datetime(mv["created_at_raw"]) or datetime.now(timezone.utc),
        ))
    db.flush()


def commit_rebuild(db: Session, spreadsheet_id: str, actor_id: int) -> RebuildBatch:
    """The destructive path. Re-validates, snapshots, clears dependents,
    truncates the mirror, re-imports, then re-exports so the DB and the
    sheet are provably identical again. All inside one transaction — if
    anything raises, nothing is committed."""
    sheet_data = _read_all_tabs(spreadsheet_id)
    parsed, counts, errors = _validate(db, sheet_data)

    batch = RebuildBatch(
        actor_id=actor_id, spreadsheet_id=spreadsheet_id,
        status=RebuildStatus.FAILED, tab_counts=json.dumps(counts), errors=json.dumps(errors),
    )
    if errors:
        db.add(batch)
        db.commit()
        return batch

    snapshot_path = _write_snapshot(db)
    try:
        _clear_dependent_tables(db)
        _truncate_managed_tables(db)
        db.flush()
        _import_all(db, parsed)
        batch.status = RebuildStatus.SUCCEEDED
        batch.snapshot_path = snapshot_path
        batch.finished_at = datetime.now(timezone.utc)
        db.add(batch)
        db.commit()
    except Exception as exc:  # noqa: BLE001 — record and re-raise after rollback
        db.rollback()
        batch.status = RebuildStatus.FAILED
        batch.errors = json.dumps([*errors, f"commit failed: {exc}"])
        batch.snapshot_path = snapshot_path
        db.add(batch)
        db.commit()
        raise

    export_all(db, spreadsheet_id)  # mirror <-> DB provably identical again
    return batch
