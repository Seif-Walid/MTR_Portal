"""The data explorer: every record in the portal, and how records connect.

Generic over the schema — relations come straight from the foreign keys in the
SQLAlchemy metadata (plus a few that the schema stores without a foreign key:
a role seat's event/team, a member's portal account), so a new table or column
shows up here without touching this module. What each person may see is the
per-domain *view* privilege of the table's group, the same privileges that
gate the rest of the portal.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Callable

from sqlalchemy import String, Text, func, or_, select
from sqlalchemy.orm import Session

from app.core.database import Base


@dataclass(frozen=True)
class Entity:
    table: str
    label: str  # plural, for lists
    singular: str
    group: str
    privilege: str
    # columns searched / used as the row's title, in priority order
    title: tuple[str, ...] = ("name",)
    # extra columns shown next to the title in lists
    summary: tuple[str, ...] = ()
    hidden: tuple[str, ...] = ()  # never exposed
    # a custom title (overrides `title`)
    title_fn: Callable[[object], str] | None = None


def _participation_title(p) -> str:
    return f"{p.event.name} — {p.member.full_name}"


def _money(n) -> str:
    return f"{(n or 0):,.0f} EGP"


def _payment_title(p) -> str:
    return f"{_money(p.amount)} · {p.member.full_name} · {p.paid_on.isoformat()}"


def _enrollment_title(e) -> str:
    return f"{e.member.full_name} — {e.tier.name} ({e.status})"


ENTITIES: list[Entity] = [
    # people
    # a person: member and account in one row
    Entity("users", "Members", "Member", "People", "people.view",
           title=("full_name", "mtr_id", "email"), summary=("email", "university", "is_active"),
           hidden=("hashed_password",), title_fn=lambda u: u.label),
    Entity("event_participations", "Participations", "Participation", "People", "members.view",
           title=("role", "team"), summary=("role", "team", "rating"), title_fn=_participation_title),
    # events
    Entity("events", "Events", "Event", "Events", "events.view",
           title=("name", "code"), summary=("code", "status", "start_date")),
    Entity("event_kinds", "Event kinds", "Event kind", "Events", "events.view",
           title=("name",), summary=("slug",)),
    Entity("event_categories", "Event categories", "Event category", "Events", "events.view"),
    Entity("event_teams", "Event teams", "Event team", "Events", "events.view",
           summary=("award",)),
    Entity("event_team_members", "Team rosters", "Team roster entry", "Events", "events.view",
           title=("role",), summary=("role",)),
    Entity("time_blocks", "Time blocks", "Time block", "Events", "events.view",
           title=("title",), summary=("start_date", "end_date")),
    # organization
    Entity("positions", "Positions", "Position", "Organization", "org.view",
           title=("title",), summary=("entity_type",)),
    Entity("position_occupants", "Seat holders", "Seat holder", "Organization", "org.view",
           title=("id",)),
    Entity("access_levels", "Access levels", "Access level", "Organization", "org.view",
           summary=("rank",), hidden=("privileges",)),
    Entity("role_templates", "Automatic roles", "Automatic role", "Organization", "org.view",
           title=("title_template",), summary=("event",)),
    # inventory
    Entity("inventory_items", "Inventory items", "Inventory item", "Inventory", "inventory.view",
           summary=("category", "quantity", "unit")),
    Entity("inventory_locations", "Locations", "Location", "Inventory", "inventory.view",
           summary=("kind",)),
    Entity("inventory_allocations", "Allocations", "Allocation", "Inventory", "inventory.view",
           title=("label", "purpose"), summary=("purpose", "quantity")),
    Entity("inventory_movements", "Stock movements", "Stock movement", "Inventory", "inventory.view",
           title=("reason",), summary=("quantity", "created_at")),
    Entity("inventory_requests", "Checkout requests", "Checkout request", "Inventory", "inventory.view",
           title=("reason",), summary=("status", "quantity")),
    # finance
    Entity("finance_seasons", "Seasons", "Season", "Finance", "finance.view",
           summary=("status", "start_date")),
    Entity("budget_lines", "Budget lines", "Budget line", "Finance", "finance.view",
           title=("item",), summary=("currency", "unit_price", "required_qty")),
    Entity("spendings", "Spendings", "Spending", "Finance", "finance.view",
           title=("item",), summary=("spent_on", "count", "unit_cost")),
    Entity("dues_tiers", "Dues tiers", "Dues tier", "Finance", "finance.view",
           summary=("monthly_fee", "months")),
    Entity("dues_discounts", "Dues discounts", "Dues discount", "Finance", "finance.view",
           title=("label",), summary=("min_years", "discount")),
    Entity("dues_enrollments", "Dues enrolments", "Dues enrolment", "Finance", "finance.view",
           title=("status",), summary=("status", "maturity_override"), title_fn=_enrollment_title),
    Entity("dues_payments", "Dues payments", "Dues payment", "Finance", "finance.view",
           title=("note",), summary=("paid_on", "amount", "note"), title_fn=_payment_title),
    Entity("funding_lines", "Funding", "Funding line", "Finance", "finance.view",
           title=("source",), summary=("amount", "status")),
    Entity("payables", "Payables", "Payable", "Finance", "finance.view",
           title=("description",), summary=("amount", "status", "due_date")),
    Entity("cash_transfers", "Cash transfers", "Cash transfer", "Finance", "finance.view",
           title=("note",), summary=("transferred_on", "amount")),
    Entity("finance_parties", "People & entities", "Party", "Finance", "finance.view",
           summary=("phone", "is_active")),
    Entity("finance_options", "Pick-list values", "Pick-list value", "Finance", "finance.view",
           title=("value",), summary=("list_key",)),
    # work — task visibility is per-person elsewhere, so here it's admin-only
    Entity("tasks", "Tasks", "Task", "Work", "users.manage",
           title=("title",), summary=("status", "priority", "due_date")),
    Entity("work_requests", "Work requests", "Work request", "Work", "users.manage",
           title=("title",), summary=("status", "priority")),
    Entity("task_comments", "Task comments", "Task comment", "Work", "users.manage",
           title=("body",)),
    Entity("audit_log", "Audit log", "Audit entry", "System", "audit.view",
           title=("action",), summary=("domain", "entity_type", "created_at")),
]
BY_TABLE = {e.table: e for e in ENTITIES}
GROUP_ORDER = ["People", "Events", "Organization", "Inventory", "Finance", "Work", "System"]


@dataclass(frozen=True)
class Link:
    """One directed relation: rows of `source` point at rows of `target` through
    `column` (optionally only where `where_col == where_val`)."""

    source: str
    column: str
    target: str
    label: str  # how the source names the target, e.g. "Manager"
    where_col: str | None = None
    where_val: str | None = None


def _pretty(col: str) -> str:
    return col.removesuffix("_id").replace("_", " ").capitalize()


def label_for(table: str, col: str) -> str:
    """A column's human name: the Data Tables grid's label when it has one
    (e.g. "MTR ID", "Governorate", "Portal account"), else a prettified name."""
    from app.domains.bulk.registry import TABLES

    for spec in TABLES.values():
        if spec.model.__table__.name != table or spec.read_only:
            continue
        for c in spec.columns:
            if c.model_attr == col and c.label:
                return c.label
    if col == "id":
        return "ID"
    is_fk = any(fk.parent.name == col for fk in Base.metadata.tables[table].foreign_keys)
    return _pretty(col) if is_fk else col.replace("_", " ").capitalize()


def _cols(table: str, names) -> list[dict]:
    return [{"name": n, "label": label_for(table, n)} for n in names]


def _links() -> list[Link]:
    out = []
    for table in Base.metadata.tables.values():
        if table.name not in BY_TABLE:
            continue
        for fk in table.foreign_keys:
            if fk.column.table.name in BY_TABLE:
                out.append(Link(table.name, fk.parent.name, fk.column.table.name, _pretty(fk.parent.name)))
    # relations stored without a foreign key: a role seat belongs to an event or a team
    out += [
        Link("positions", "entity_id", "events", "Event", "entity_type", "event"),
        Link("positions", "entity_id", "event_teams", "Team", "entity_type", "team"),
    ]
    return out


class _Lazy(list):
    """The relation list, built on first use — after every model module has
    been imported, whatever order the routers were mounted in."""

    def _fill(self):
        if not self:
            self.extend(_links())

    def __iter__(self):
        self._fill()
        return super().__iter__()


LINKS = _Lazy()

# A pure join table is shown as the thing on its far side, not as itself.
JOIN_TABLES = {"position_occupants", "event_team_members"}


def model_for(table: str):
    for mapper in Base.registry.mappers:
        if mapper.class_.__table__.name == table:
            return mapper.class_
    return None


# --- privileges ---------------------------------------------------------------
def visible_tables(privileges: set[str]) -> set[str]:
    return {e.table for e in ENTITIES if e.privilege in privileges}


def restricted_columns(table: str, privileges: set[str] | None) -> set[str]:
    """Columns of `table` this viewer may not see — the bulk registry's
    column-level view privileges (e.g. member contact details), applied here too."""
    from app.domains.bulk.registry import restricted_attrs

    return set() if privileges is None else restricted_attrs(table, privileges)


def edit_keys(privileges: set[str]) -> dict[str, tuple[str, set[str]]]:
    """SQL table -> (bulk-editor table key, its editable columns) for every
    table this viewer may edit in place. Only whole-table specs count: a
    filtered one (a single pick-list of finance_options) can't stand for the
    table."""
    from app.domains.bulk.registry import REFS, TABLES

    out: dict[str, tuple[str, set[str]]] = {}
    for spec in TABLES.values():
        if spec.read_only or spec.where is not None or spec.privilege not in privileges:
            continue
        # a column can pin a related list only if the grid stores the raw id under the SQL name
        cols = {c.name for c in spec.columns if c.editable and c.name == c.model_attr
                and (c.ref is None or REFS[c.ref].value_attr == "id")}
        out.setdefault(spec.model.__table__.name, (spec.key, cols))
    return out


def annotate_edit(rec: dict, editable: dict[str, tuple[str, set[str]]], visible: set[str]) -> dict:
    """Mark what of a record view can be edited in place: the record itself,
    each related list whose rows point straight at it (edited with that pointer
    fixed), and the related lists it has none of yet (offered as "add")."""
    table, rid = rec["table"], rec["id"]
    rec["edit"] = editable.get(table, (None,))[0]
    shown: set[tuple[str, str]] = set()
    for g in rec["incoming"]:
        source, _, column = g["key"].partition(".")
        if g["via"] or source in JOIN_TABLES:
            continue
        shown.add((source, column))
        target = editable.get(source)
        if target and column in target[1]:
            g["edit"], g["fk"] = target[0], column
    addable = []
    for link in LINKS:
        if link.target != table or link.where_col or link.source in JOIN_TABLES:
            continue
        if link.source not in visible or (link.source, link.column) in shown:
            continue
        target = editable.get(link.source)
        if target and link.column in target[1]:
            src = BY_TABLE[link.source]
            many = sum(1 for l in LINKS if l.source == link.source and l.target == table) > 1
            addable.append({
                "key": f"{link.source}.{link.column}",
                "label": f"{src.label} ({link.label.lower()})" if many else src.label,
                "table": link.source, "edit": target[0], "fk": link.column, "id": rid,
            })
    rec["addable"] = addable
    return rec


# --- values -------------------------------------------------------------------
def _json(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value) or None
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def title_of(entity: Entity, obj) -> str:
    if entity.title_fn is not None:
        return entity.title_fn(obj)
    for col in entity.title:
        v = getattr(obj, col, None)
        if v not in (None, ""):
            return str(_json(v))
    return f"{entity.singular} #{obj.id}"


class Titles:
    """Batch title lookups so a page of links costs one query per table."""

    def __init__(self, db: Session):
        self.db = db
        self.cache: dict[tuple[str, int], str] = {}

    def get(self, table: str, ids: set[int]) -> dict[int, str]:
        missing = [i for i in ids if (table, i) not in self.cache]
        if missing:
            model, entity = model_for(table), BY_TABLE[table]
            for obj in self.db.scalars(select(model).where(model.id.in_(missing))).unique():
                self.cache[(table, obj.id)] = title_of(entity, obj)
        return {i: self.cache.get((table, i), f"#{i}") for i in ids}


def _columns(entity: Entity) -> list[str]:
    table = Base.metadata.tables[entity.table]
    return [c.name for c in table.columns if c.name not in entity.hidden]


def _link_for(source: str, column: str, obj) -> Link | None:
    for link in LINKS:
        if link.source != source or link.column != column:
            continue
        if link.where_col and getattr(obj, link.where_col, None) != link.where_val:
            continue
        return link
    return None


def summary_row(entity: Entity, obj) -> dict:
    fields = {}
    for col in entity.summary:
        fields[col] = _json(getattr(obj, col, None))
    return {"id": obj.id, "title": title_of(entity, obj), "fields": fields}


def _live(model) -> list:
    """Soft-deleted rows (deleted_at set) are gone as far as browsing goes."""
    return [model.deleted_at.is_(None)] if hasattr(model, "deleted_at") else []


# --- schema ---------------------------------------------------------------------
def schema(db: Session, visible: set[str], editable: dict | None = None) -> dict:
    editable = editable or {}
    entities = []
    for e in ENTITIES:
        if e.table not in visible:
            continue
        model = model_for(e.table)
        count = db.scalar(select(func.count()).select_from(model).where(*_live(model))) or 0
        entities.append({
            "table": e.table, "label": e.label, "singular": e.singular, "group": e.group,
            "count": count, "summary": list(e.summary),
            "edit": editable.get(e.table, (None,))[0],
        })
    links = [
        {"source": l.source, "column": l.column, "target": l.target, "label": l.label}
        for l in LINKS
        if l.source in visible and l.target in visible and l.source != l.target
    ]
    groups = [g for g in GROUP_ORDER if any(x["group"] == g for x in entities)]
    return {"groups": groups, "entities": entities, "links": links}


# --- lists ------------------------------------------------------------------------
def _search_clause(model, entity: Entity, q: str, privileges: set[str] | None = None):
    table = Base.metadata.tables[entity.table]
    hidden = set(entity.hidden) | restricted_columns(entity.table, privileges)
    cols = []
    for name in (*entity.title, *entity.summary, "email", "mtr_id", "code", "phone"):
        col = table.columns.get(name)
        if col is not None and isinstance(col.type, (String, Text)) and name not in hidden:
            cols.append(getattr(model, name))
    if q.isdigit():
        cols_id = [model.id == int(q)]
    else:
        cols_id = []
    like = f"%{q.lower()}%"
    clauses = [*cols_id, *[func.lower(c).like(like) for c in dict.fromkeys(cols)]]
    return or_(*clauses) if clauses else None


def list_rows(db: Session, entity: Entity, q: str, offset: int, limit: int, visible: set[str],
              privileges: set[str] | None = None) -> dict:
    model = model_for(entity.table)
    query = select(model).where(*_live(model))
    if q:
        clause = _search_clause(model, entity, q, privileges)
        if clause is None:
            return {"total": 0, "rows": []}
        query = query.where(clause)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = list(db.scalars(query.order_by(model.id.desc() if entity.group in ("Work", "System") else model.id)
                           .offset(offset).limit(limit)).unique())
    return {
        "total": total,
        "columns": _cols(entity.table, entity.summary),
        "rows": [summary_row(entity, o) for o in rows],
    }


def search(db: Session, q: str, visible: set[str], per_table: int = 6, privileges: set[str] | None = None) -> list[dict]:
    out = []
    for e in ENTITIES:
        if e.table not in visible or e.table in JOIN_TABLES:
            continue
        model = model_for(e.table)
        clause = _search_clause(model, e, q, privileges)
        if clause is None:
            continue
        rows = list(db.scalars(select(model).where(clause, *_live(model)).limit(per_table)).unique())
        if rows:
            out.append({
                "table": e.table, "label": e.label, "group": e.group,
                "rows": [{"id": r.id, "title": title_of(e, r)} for r in rows],
            })
    return out


# --- one record -------------------------------------------------------------------
RELATED_LIMIT = 100

def _incoming(db: Session, table: str, rid: int, visible: set[str], titles: Titles, via: str | None = None) -> list[dict]:
    groups = []
    for link in LINKS:
        if link.target != table or link.source not in visible:
            continue
        src_entity = BY_TABLE[link.source]
        model = model_for(link.source)
        cond = [getattr(model, link.column) == rid, *_live(model)]
        if link.where_col:
            cond.append(getattr(model, link.where_col) == link.where_val)
        total = db.scalar(select(func.count()).select_from(model).where(*cond)) or 0
        if not total:
            continue
        rows = list(db.scalars(select(model).where(*cond).order_by(model.id).limit(RELATED_LIMIT)).unique())

        if link.source in JOIN_TABLES:
            # show the far side of the join (the user in a seat, the seat of a user, …)
            far = next((l for l in LINKS if l.source == link.source and l.column != link.column), None)
            if far is None or far.target not in visible:
                continue
            ids = {getattr(r, far.column) for r in rows if getattr(r, far.column) is not None}
            names = titles.get(far.target, ids)
            extra = list(BY_TABLE[link.source].summary)
            groups.append({
                "key": f"{link.source}.{link.column}{'@' + via if via else ''}",
                "label": BY_TABLE[far.target].label if link.source != "event_team_members" or far.target != "users"
                else "Team members",
                "table": far.target,
                "relation": f"{BY_TABLE[link.source].label}",
                "via": via,
                "total": total,
                "columns": _cols(link.source, extra),
                "rows": [
                    {"id": getattr(r, far.column), "title": names.get(getattr(r, far.column), "—"),
                     "fields": {c: _json(getattr(r, c, None)) for c in extra}}
                    for r in rows if getattr(r, far.column) is not None
                ],
            })
            continue

        groups.append({
            "key": f"{link.source}.{link.column}{'@' + via if via else ''}",
            "label": src_entity.label if sum(1 for l in LINKS if l.source == link.source and l.target == table) == 1
            else f"{src_entity.label} ({link.label.lower()})",
            "table": link.source,
            "relation": link.label,
            "via": via,
            "total": total,
            "columns": _cols(link.source, src_entity.summary),
            "rows": [summary_row(src_entity, r) for r in rows],
        })
    return groups


def record(db: Session, entity: Entity, rid: int, visible: set[str], privileges: set[str] | None = None) -> dict | None:
    model = model_for(entity.table)
    obj = db.get(model, rid)
    if obj is None:
        return None
    titles = Titles(db)

    # fields, with outgoing references resolved to links
    fields = []
    outgoing = []
    restricted = restricted_columns(entity.table, privileges)
    for col in _columns(entity):
        if col in restricted:
            continue
        value = getattr(obj, col, None)
        link = _link_for(entity.table, col, obj)
        if link is not None:
            if link.target not in visible:
                continue
            label = label_for(entity.table, col) if link.where_col is None else link.label
            if value is None:
                fields.append({"name": col, "label": label, "value": None})
                continue
            title = titles.get(link.target, {value})[value]
            ref = {"table": link.target, "id": value, "title": title, "entity": BY_TABLE[link.target].singular}
            fields.append({"name": col, "label": label, "value": title, "link": ref})
            outgoing.append({**ref, "relation": label})
            continue
        if col in ("entity_type",) or (col == "entity_id" and entity.table == "positions"):
            continue
        fields.append({"name": col, "label": label_for(entity.table, col), "value": _json(value)})

    # computed values the model exposes (FMV, needed cost, net, display name …)
    for prop in ("unit_price_egp", "total_qty", "needed_qty", "fmv", "needed_cost", "net"):
        if hasattr(type(obj), prop) and isinstance(getattr(type(obj), prop), property):
            fields.append({"name": prop, "label": label_for(entity.table, prop), "value": _json(getattr(obj, prop)), "computed": True})

    incoming = _incoming(db, entity.table, rid, visible, titles)

    return {
        "table": entity.table,
        "entity": entity.singular,
        "group": entity.group,
        "id": rid,
        "title": title_of(entity, obj),
        "fields": fields,
        "outgoing": outgoing,
        "incoming": incoming,
    }
