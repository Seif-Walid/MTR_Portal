"""The bulk-editor table registry: a data-driven description of every DB
table an admin can mass-edit in the portal grid.

One `TableSpec` per table declares its columns (type, editability, foreign-key
reference), the existing per-domain privilege that gates it, and how a deleted
row is handled. A single generic validate/apply engine in `service.py` drives
every table off this registry — there is no per-table screen or endpoint.

Column layouts and row serialization are deliberately shared with the Sheets
mirror: reads reuse `sync.service._EXPORTERS`, so the grid, the CSV template and
the Google-Sheets export always agree on shape.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Literal

from app.domains.access.models import AccessLevel
from app.domains.events.models import (
    Event,
    EventCategory,
    EventKind,
    EventStatus,
    EventTeam,
)
from app.domains.inventory.models import (
    Condition,
    InventoryItem,
    Location,
    LocationKind,
    StockMovement,
)
from app.domains.positions.models import Position
from app.domains.users.models import Department, MemberProfile, User

ColType = Literal["int", "str", "bool", "date", "datetime"]


@dataclass(frozen=True)
class Ref:
    """A foreign-key target: which model a reference column points at, whether
    it is matched by id/name/slug, and how to label a choice in the grid's
    dropdown."""

    model: type
    value_attr: str  # "id" | "name" | "slug" — the value stored in the cell
    label: Callable[[object], str]


# Reference targets, keyed by the name a Column.ref points to.
REFS: dict[str, Ref] = {
    "user": Ref(User, "id", lambda u: f"{u.full_name} <{u.email}>"),
    "access_level": Ref(AccessLevel, "name", lambda l: l.name),
    "event_kind": Ref(EventKind, "slug", lambda k: f"{k.slug} — {k.name}"),
    "position": Ref(Position, "id", lambda p: p.title),
    "event": Ref(Event, "id", lambda e: e.name),
    "event_category": Ref(EventCategory, "id", lambda c: c.name),
    "event_team": Ref(EventTeam, "id", lambda t: t.name),
    "location": Ref(Location, "id", lambda l: l.name),
    "item": Ref(InventoryItem, "id", lambda i: i.name),
}


@dataclass(frozen=True)
class Column:
    name: str  # must match the sync exporter header exactly
    type: ColType = "str"
    editable: bool = True  # False -> shown read-only (ids, derived, joins)
    required: bool = False
    ref: str | None = None  # key into REFS
    attr: str | None = None  # model attribute to write (defaults to `name`)
    choices: tuple[str, ...] | None = None  # fixed enum values

    @property
    def model_attr(self) -> str:
        return self.attr or self.name


DeletePolicy = Literal["soft", "deactivate", "hard", "none"]


@dataclass
class TableSpec:
    key: str  # matches sync TAB_ORDER
    label: str
    model: type
    columns: list[Column]
    privilege: str  # existing per-domain edit privilege
    delete: DeletePolicy
    # read_only tables are the auto-registered "every other table" specs: shown
    # in the grid for inspection, but no editing / Sheets round-trip / delete.
    read_only: bool = False
    # append_only tables (the movements ledger) accept new rows only: existing
    # rows are locked and deletes are refused.
    append_only: bool = False
    # optional per-table guard run before a hard/soft delete; returns a blocking
    # message or None. Populated in service.py to avoid import cycles.
    delete_guard: Callable[[object, int], str | None] | None = field(default=None, repr=False)

    def column(self, name: str) -> Column | None:
        return next((c for c in self.columns if c.name == name), None)


def _enum(e) -> tuple[str, ...]:
    return tuple(v.value for v in e)


# --- the tables -------------------------------------------------------------
# Column order mirrors the matching sync._EXPORTERS header exactly.
TABLES: dict[str, TableSpec] = {
    "people": TableSpec(
        key="people", label="People", model=User, privilege="users.manage", delete="deactivate",
        columns=[
            Column("id", "int", editable=False),
            Column("email", "str", required=True),
            Column("full_name", "str", required=True),
            Column("department", "str", choices=_enum(Department)),
            Column("access_level", ref="access_level", attr="access_level_id"),
            Column("manager_id", "int", ref="user"),
            Column("is_active", "bool"),
        ],
    ),
    "member_profiles": TableSpec(
        # The roster record behind an account (mtr_id, contact, biographical
        # fields). Gated at users.manage since it holds member PII (national_id).
        # delete="none": a roster row is bound 1:1 to an account, so it is
        # removed by deactivating the person on the People tab — never deleted
        # on its own — which keeps a stray sheet-side row deletion from wiping
        # roster data (the push just re-adds it).
        key="member_profiles", label="Member Profiles", model=MemberProfile,
        privilege="users.manage", delete="none",
        columns=[
            Column("id", "int", editable=False),
            Column("user_id", "int", ref="user", required=True),
            Column("mtr_id", "str"),
            Column("national_id", "str"),
            Column("birthday", "date"),
            Column("university", "str"),
            Column("college", "str"),
            Column("major", "str"),
            Column("graduating_year", "int"),
            Column("phone", "str"),
            Column("guardian_phone", "str"),
            Column("uni_id", "str"),
            Column("location", "str"),
        ],
    ),
    "positions": TableSpec(
        key="positions", label="Org Positions", model=Position, privilege="org.edit", delete="hard",
        columns=[
            Column("id", "int", editable=False),
            Column("title", "str", required=True),
            Column("parent_id", "int", ref="position"),
            Column("occupant_ids", "str", editable=False),  # join column — edit on the Org page
            Column("is_technical", "bool"),
            Column("access_level", ref="access_level", attr="access_level_id"),
        ],
    ),
    "event_kinds": TableSpec(
        key="event_kinds", label="Event Kinds", model=EventKind, privilege="org.edit", delete="hard",
        columns=[
            Column("id", "int", editable=False),
            Column("slug", "str", required=True),
            Column("name", "str", required=True),
            Column("event_label", "str"),
            Column("category_label", "str"),
            Column("team_label", "str"),
            Column("member_label", "str"),
            Column("sort_order", "int"),
        ],
    ),
    "events": TableSpec(
        key="events", label="Events", model=Event, privilege="events.manage_any", delete="hard",
        columns=[
            Column("id", "int", editable=False),
            Column("name", "str", required=True),
            # The official long-form title the public Hall of Fame heads the
            # record with; blank when `name` is the only name.
            Column("full_name", "str"),
            Column("kind", ref="event_kind", attr="kind_id"),
            Column("description", "str"),
            Column("start_date", "date"),
            Column("end_date", "date"),
            Column("status", "str", choices=_enum(EventStatus)),
        ],
    ),
    "event_categories": TableSpec(
        key="event_categories", label="Event Categories", model=EventCategory,
        privilege="events.manage_any", delete="hard",
        columns=[
            Column("id", "int", editable=False),
            Column("event_id", "int", ref="event", required=True),
            Column("name", "str", required=True),
        ],
    ),
    "event_teams": TableSpec(
        key="event_teams", label="Event Teams", model=EventTeam,
        privilege="events.manage_any", delete="soft",
        columns=[
            Column("id", "int", editable=False),
            Column("category_id", "int", ref="event_category", required=True),
            Column("name", "str", required=True),
            # Per-team placement published in the Hall of Fame, e.g. "🥇 1st Place".
            Column("award", "str"),
        ],
    ),
    # NB: no "event_team_members" grid — that flat roster is unused; event
    # membership is held as role/position occupants (see the Org Positions
    # table and the event card's member count), so surfacing an always-empty
    # roster here only confused it with real membership.
    "inventory_locations": TableSpec(
        key="inventory_locations", label="Inventory Locations", model=Location,
        privilege="inventory.edit", delete="hard",
        columns=[
            Column("id", "int", editable=False),
            Column("name", "str", required=True),
            Column("kind", "str", choices=_enum(LocationKind)),
            Column("notes", "str"),
        ],
    ),
    "inventory_items": TableSpec(
        key="inventory_items", label="Inventory Items", model=InventoryItem,
        privilege="inventory.edit", delete="soft",
        columns=[
            Column("id", "int", editable=False),
            Column("name", "str", required=True),
            Column("category", "str"),
            Column("asset_tag", "str"),
            Column("sku", "str"),
            Column("quantity", "int", required=True),
            Column("low_stock_threshold", "int"),
            Column("unit", "str"),
            Column("location", "str"),  # free-text location note, not the FK
            Column("condition", "str", choices=_enum(Condition)),
            Column("notes", "str"),
            Column("team_lead_id", "int", ref="user"),
        ],
    ),
    "inventory_movements": TableSpec(
        key="inventory_movements", label="Inventory Movements (ledger)", model=StockMovement,
        privilege="inventory.edit", delete="none", append_only=True,
        columns=[
            Column("id", "int", editable=False),
            Column("item_id", "int", ref="item", required=True),
            Column("quantity", "int", required=True),
            Column("from_location_id", "int", ref="location"),
            Column("from_holder_id", "int", ref="user"),
            Column("to_location_id", "int", ref="location"),
            Column("to_holder_id", "int", ref="user"),
            Column("actor_id", "int", ref="user"),
            Column("reason", "str"),
            Column("created_at", "datetime", editable=False),
        ],
    ),
}


# --- read-only auto-registration -------------------------------------------
# Everything above is a hand-tuned, editable grid. Admins also want to *see*
# every other table on the server (auth sessions, audit log, role templates,
# position occupants, …). We reflect each remaining mapped table into a
# read-only TableSpec so the same generic grid can display it. These are
# gated behind "users.manage" (top-admin only) since they include sensitive
# internal tables, and they carry no editing, delete or Sheets round-trip.
_READONLY_PRIVILEGE = "users.manage"
_readonly_loaded = False


def _prettify(table_name: str) -> str:
    return table_name.replace("_", " ").title()


def ensure_all_tables_registered() -> None:
    """Idempotently add a read-only spec for every mapped table not already
    curated above. Imports all domain model modules first so SQLAlchemy knows
    about every table, then registers the leftovers. Cheap after the first run."""
    global _readonly_loaded
    if _readonly_loaded:
        return

    import importlib
    import pkgutil

    import app.domains as _domains

    for mod in pkgutil.walk_packages(_domains.__path__, "app.domains."):
        if mod.name.endswith(".models"):
            importlib.import_module(mod.name)

    from app.core.database import Base

    curated = {spec.model.__table__.name for spec in TABLES.values()}
    autos: list[TableSpec] = []
    seen: set[str] = set()
    for mapper in Base.registry.mappers:
        cls = mapper.class_
        table = cls.__table__
        name = table.name
        if name in TABLES or name in curated or name in seen:
            continue
        seen.add(name)
        autos.append(
            TableSpec(
                key=name,
                label=_prettify(name),
                model=cls,
                columns=[Column(c.key, "str", editable=False) for c in table.columns],
                privilege=_READONLY_PRIVILEGE,
                delete="none",
                read_only=True,
            )
        )
    for spec in sorted(autos, key=lambda s: s.label):
        TABLES[spec.key] = spec
    _readonly_loaded = True
