"""Generic bulk-editor engine: read / validate / apply for any table in the
registry.

This is an **incremental, id-keyed upsert**: rows carrying an id are updated, rows without one are inserted, and
ids listed in `deletes` are removed per the table's delete policy. A save is
all-or-nothing — if validation finds any problem, nothing is written.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import date, datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.domains.access.models import AccessLevel
from app.domains.audit import service as audit
from app.domains.events.models import Event, EventCategory, EventTeam, EventTeamMember
from app.domains.inventory.models import InventoryItem, StockMovement
from app.domains.positions.models import Position, PositionOccupant
from app.domains.users.models import User
from app.domains.bulk.exporters import _EXPORTERS, _bool, _parse_date, _parse_datetime
from app.domains.bulk.registry import REFS, TABLES, Column, TableSpec


# --- reads ------------------------------------------------------------------
# Read-only auto-registered tables are capped so a huge table (audit log,
# notifications) can't blow up one response.
_READONLY_ROW_CAP = 2000


def _cell(value: object) -> str:
    """Stringify any DB value into the grid's string-cell convention."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else f"{value:.4f}".rstrip("0").rstrip(".")
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _generic_export(db: Session, spec: TableSpec) -> tuple[list[str], list[list[str]]]:
    """Reflect any mapped table into (header, rows) without a hand-written
    exporter — used for the read-only 'every table' specs."""
    model = spec.model
    cols = [c.key for c in model.__table__.columns]
    objs = db.scalars(select(model).limit(_READONLY_ROW_CAP))
    rows = [[_cell(getattr(o, c)) for c in cols] for o in objs]
    return cols, rows


def _spec_query(spec: TableSpec):
    return select(spec.model).where(*spec.filters()).order_by(spec.model.id)


def _spec_ids(db: Session, spec: TableSpec) -> set[int]:
    return {r[0] for r in db.execute(select(spec.model.id).where(*spec.filters())).all()}


def _spec_export(db: Session, spec: TableSpec) -> tuple[list[str], list[list[str]]]:
    """Read a curated table straight off its column declarations — attribute
    per column (computed @property columns included), id refs as ids and
    name/slug refs translated to the referenced row's name/slug."""
    header = [c.name for c in spec.columns]
    lookups: dict[str, dict[int, object]] = {}
    for c in spec.columns:
        if c.ref and REFS[c.ref].value_attr != "id" and c.ref not in lookups:
            ref = REFS[c.ref]
            lookups[c.ref] = {o.id: getattr(o, ref.value_attr) for o in db.scalars(select(ref.model))}
    rows = []
    for obj in db.scalars(_spec_query(spec)).unique():
        row = []
        for c in spec.columns:
            value = getattr(obj, c.model_attr)
            if c.ref in lookups and value is not None:
                value = lookups[c.ref].get(value)
            row.append(_cell(value))
        rows.append(row)
    return header, rows


def _export_for(db: Session, spec: TableSpec) -> tuple[list[str], list[list[str]]]:
    exporter = _EXPORTERS.get(spec.key)
    if exporter:
        return exporter(db)
    return _generic_export(db, spec) if spec.read_only else _spec_export(db, spec)


def read_table(db: Session, spec: TableSpec) -> dict:
    """Current DB rows for a table, plus the dropdown options every reference
    column needs. Row serialization is the exact same code the Excel export
    uses, so grid and file never disagree."""
    columns = [_column_payload(c) for c in spec.columns]
    row_dicts = table_rows(db, spec)
    return {
        "key": spec.key,
        "label": spec.label,
        "columns": columns,
        "rows": row_dicts,
        "options": _ref_options(db, spec),
        "append_only": spec.append_only,
        "delete": spec.delete,
        "read_only": spec.read_only,
        "group": spec.group,
        "description": spec.description,
        "locked": ({"column": spec.period_attr, "values": [str(i) for i in _closed_periods(db, spec)]}
                   if spec.period_attr else None),
    }


def _closed_periods(db: Session, spec: TableSpec) -> dict[int, str]:
    """{season id: name} of the closed / cancelled seasons — their rows are frozen."""
    if not spec.period_attr:
        return {}
    from app.domains.finance.models import FinanceSeason, SeasonStatus

    frozen = (SeasonStatus.CLOSED.value, SeasonStatus.CANCELLED.value)
    return {s.id: s.name for s in db.scalars(select(FinanceSeason).where(FinanceSeason.status.in_(frozen)))}


def _column_payload(c: Column) -> dict:
    return {
        "name": c.name,
        "label": c.header,
        "type": c.type,
        "editable": c.editable,
        "required": c.required,
        "ref": c.ref,
        "choices": list(c.choices) if c.choices else None,
        "min": c.min,
        "max": c.max,
        "max_length": c.max_length,
        "pattern": c.pattern,
        "pattern_hint": c.pattern_hint,
    }


def _ref_options(db: Session, spec: TableSpec) -> dict[str, list[dict]]:
    """{column_name: [{value, label}, ...]} for every reference column, so the
    grid can render searchable dropdowns and match ids to human labels."""
    out: dict[str, list[dict]] = {}
    for col in spec.columns:
        if not col.ref or col.ref in out:
            continue
        ref = REFS[col.ref]
        opts = [
            {"value": getattr(o, ref.value_attr), "label": ref.label(o)}
            for o in db.scalars(ref.query()).unique()
        ]
        out[col.name] = opts
    return out


# --- validation -------------------------------------------------------------
@dataclass
class Coerced:
    """One validated incoming row: model attribute -> python value, ready to
    write. `index` is the row's position in the submitted array (for anchoring
    errors back to the grid); `id` is the existing row id, or None for inserts."""

    index: int
    id: int | None
    fields: dict


def _err(errors: list[dict], index: int | None, column: str | None, message: str, **extra) -> None:
    errors.append({"row": index, "column": column, "message": message, **extra})


def _last_editor(db: Session, spec: TableSpec, rid: int) -> str | None:
    from app.domains.audit.models import AuditLog

    entry = db.scalars(
        select(AuditLog)
        .where(AuditLog.domain == "bulk", AuditLog.entity_type == spec.key, AuditLog.entity_id == rid)
        .order_by(AuditLog.id.desc())
        .limit(1)
    ).first()
    if entry is None or entry.actor_id is None:
        return None
    user = db.get(User, entry.actor_id)
    return user.full_name if user else None


def _valid_ref_ids(db: Session, ref_key: str, deleted: dict[str, set[int]]) -> set[int]:
    ref = REFS[ref_key]
    q = select(ref.model.id)
    if ref.where is not None:
        q = q.where(ref.where())
    ids = {r[0] for r in db.execute(q).all()}
    # A reference must not point at a row being deleted in the same save.
    return ids - deleted.get(_model_table_key(ref.model), set())


def _name_map(db: Session, ref_key: str) -> dict[str, int]:
    ref = REFS[ref_key]
    return {getattr(o, ref.value_attr): o.id for o in db.scalars(select(ref.model))}


def _model_table_key(model: type) -> str:
    return next((k for k, s in TABLES.items() if s.model is model), "")


_UNSET = object()


def _column_info(model: type) -> dict[str, tuple[bool, object]]:
    """attr -> (nullable, scalar_default). Lets a blank cell fall back to the
    DB column's own default instead of writing NULL into a NOT NULL column."""
    info: dict[str, tuple[bool, object]] = {}
    for col in model.__table__.columns:
        scalar = _UNSET
        d = col.default
        if d is not None and getattr(d, "is_scalar", False):
            scalar = d.arg
        info[col.key] = (col.nullable, scalar)
    return info


def rule_error(col: Column, value) -> str | None:
    """Why `value` breaks the column's input rules, or None."""
    import re

    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if col.min is not None and value < col.min:
            return f"must be at least {col.min:g}"
        if col.max is not None and value > col.max:
            return f"must be at most {col.max:g}"
    if isinstance(value, str):
        if col.max_length is not None and len(value) > col.max_length:
            return f"must be at most {col.max_length} characters"
        if col.pattern and not re.fullmatch(col.pattern, value.strip()):
            return f"should be {col.pattern_hint}" if col.pattern_hint else "is not in the expected format"
    return None


def _coerce_scalar(raw: str, col: Column):
    raw = (raw or "").strip()
    if raw == "":
        return None
    if col.type == "int":
        return int(raw)
    if col.type == "number":
        return float(raw.replace(",", ""))
    if col.type == "bool":
        return _bool(raw)
    if col.type == "date":
        return _parse_date(raw)
    if col.type == "datetime":
        return _parse_datetime(raw)
    return raw


def validate(
    db: Session, spec: TableSpec, rows: list[dict], deletes: list[int]
) -> tuple[list[Coerced], list[dict], dict]:
    """Pure — never writes. Returns (coerced rows, errors, summary)."""
    errors: list[dict] = []
    existing_ids = _spec_ids(db, spec)
    deleted_by_table = {spec.key: set(deletes)}
    col_info = _column_info(spec.model)

    # pre-build reference lookups once
    id_ref_sets: dict[str, set[int]] = {}
    name_ref_maps: dict[str, dict[str, int]] = {}
    for col in spec.columns:
        if not col.ref:
            continue
        ref = REFS[col.ref]
        if ref.value_attr == "id":
            id_ref_sets.setdefault(col.ref, _valid_ref_ids(db, col.ref, deleted_by_table))
        else:
            name_ref_maps.setdefault(col.ref, _name_map(db, col.ref))

    # optimistic concurrency, per cell: an update may carry `_base` — the value
    # each edited cell had when the editor loaded it. If the database has moved
    # on since (someone else saved that cell), the cell is a conflict and is not
    # written; the row's other cells still are.
    current = _rows_by_id(db, spec) if any(isinstance(r.get("_base"), dict) for r in rows) else {}
    closed = _closed_periods(db, spec)

    coerced: list[Coerced] = []
    adds = updates = 0
    for i, row in enumerate(rows):
        raw_id = str(row.get("id", "")).strip()
        row_id: int | None = int(raw_id) if raw_id else None
        if row_id is not None and row_id not in existing_ids:
            _err(errors, i, "id", f"row id {row_id} does not exist (leave id blank to add a new row)")
            continue
        if row_id is not None and spec.append_only:
            # existing ledger rows are immutable — skip silently, no update
            continue

        base = row.get("_base") if row_id is not None and isinstance(row.get("_base"), dict) else {}
        fields: dict = {}
        row_ok = True
        for col in spec.columns:
            if not col.editable:
                continue
            if col.name in base and col.name in row:
                now = current.get(row_id, {}).get(col.name, "")
                if now != str(base[col.name] or "") and now != str(row[col.name] or "").strip():
                    _err(errors, i, col.name, "Someone else changed this cell since you loaded it",
                         code="conflict", current=now, by=_last_editor(db, spec, row_id))
                    continue
            # an update only touches the cells it sends (the grid sends just what
            # changed); a new row is read in full, blanks included
            if row_id is not None and col.name not in row:
                continue
            try:
                value = _coerce_scalar(row.get(col.name, ""), col)
            except (ValueError, TypeError):
                _err(errors, i, col.name, f"'{row.get(col.name)}' is not a valid {col.type}")
                row_ok = False
                continue

            if value is None and col.required:
                _err(errors, i, col.name, f"{col.name} is required")
                row_ok = False
                continue
            broken = rule_error(col, value)
            if broken and row_id is not None:
                # rules guard new input: a value already stored (legacy data) can be
                # sent back untouched — e.g. by a whole-sheet upload — without failing
                obj = db.get(spec.model, row_id)
                if obj is not None and getattr(obj, col.model_attr, None) == value:
                    broken = None
            if broken:
                _err(errors, i, col.name, f"{col.header} {broken}")
                row_ok = False
                continue
            if col.choices and value is not None and value not in col.choices:
                _err(errors, i, col.name, f"{value!r} must be one of: {', '.join(col.choices)}")
                row_ok = False
                continue

            if col.ref and value is not None:
                ref = REFS[col.ref]
                if ref.value_attr == "id":
                    if value not in id_ref_sets[col.ref]:
                        _err(errors, i, col.name, f"{col.name}={value} does not resolve")
                        row_ok = False
                        continue
                    fields[col.model_attr] = value
                else:
                    mapped = name_ref_maps[col.ref].get(value)
                    if mapped is None:
                        _err(errors, i, col.name, f"unknown {col.ref}: {value!r}")
                        row_ok = False
                        continue
                    fields[col.model_attr] = mapped
            elif value is None:
                # a blank cell: keep NULL if the column allows it, otherwise fall
                # back to the column's own default rather than writing NULL. If a
                # NOT NULL column has no scalar default, leave it unset (insert
                # uses the model default; update keeps the existing value).
                nullable, scalar = col_info.get(col.model_attr, (True, _UNSET))
                if nullable:
                    fields[col.model_attr] = None
                elif scalar is not _UNSET:
                    fields[col.model_attr] = scalar() if callable(scalar) else scalar
                # else: skip -> not written
            else:
                fields[col.model_attr] = value

        if not row_ok:
            continue
        if closed:
            was = getattr(db.get(spec.model, row_id), spec.period_attr, None) if row_id is not None else None
            goes = fields.get(spec.period_attr, was)
            frozen = was if was in closed else goes if goes in closed else None
            if frozen is not None:
                _err(errors, i, spec.period_attr if goes in closed and goes != was else None,
                     f"Season “{closed[frozen]}” is closed — reopen it on the Seasons table to change its rows")
                continue
        coerced.append(Coerced(index=i, id=row_id, fields=fields))
        if row_id is None:
            adds += 1
        else:
            updates += 1

    # deletes
    valid_deletes = 0
    for did in deletes:
        if spec.append_only or spec.delete == "none":
            _err(errors, None, None, f"{spec.label} rows cannot be deleted (append-only ledger)")
            break
        if did not in existing_ids:
            _err(errors, None, None, f"cannot delete id {did}: it does not exist")
            continue
        guard = spec.delete_guard(db, did) if spec.delete_guard else None
        if closed and getattr(db.get(spec.model, did), spec.period_attr, None) in closed:
            guard = f"cannot delete id {did}: its season is closed"
        if guard:
            _err(errors, None, None, guard)
            continue
        valid_deletes += 1

    summary = {"adds": adds, "updates": updates, "deletes": valid_deletes}
    return coerced, errors, summary


# --- apply ------------------------------------------------------------------
def apply(
    db: Session, spec: TableSpec, rows: list[dict], deletes: list[int], actor_id: int,
    partial: bool = False,
) -> dict:
    """Re-validate, then upsert + delete in one transaction.

    Default is all-or-nothing: any error aborts and nothing is written. With
    `partial`, every row that validates is written and the rest come back as
    errors — each row in its own savepoint, so a database constraint tripped by
    one row (a duplicate unique value) only fails that row."""
    coerced, errors, _ = validate(db, spec, rows, deletes)
    blocked_deletes = any(e["row"] is None for e in errors)
    if errors and not partial:
        return {"ok": False, "errors": errors, "summary": {"adds": 0, "updates": 0, "deletes": 0}, "ids": {}}

    # grid-shaped rows before the write — the audit trail's "old" values and
    # the full snapshot a deleted row can be restored from
    before = _rows_by_id(db, spec) if (coerced or deletes) else {}

    adds = updates = removed = 0
    ids: dict[int, int] = {}
    created: set[int] = set()
    updated: set[int] = set()
    for c in coerced:
        try:
            with db.begin_nested():
                if c.id is None:
                    obj = spec.model(**_insert_defaults(spec, c.fields))
                    db.add(obj)
                    db.flush()
                    adds += 1
                    created.add(obj.id)
                else:
                    obj = db.get(spec.model, c.id)
                    changed = False
                    for attr, value in c.fields.items():
                        if getattr(obj, attr) != value:
                            setattr(obj, attr, value)
                            changed = True
                    if changed:  # untouched rows are a silent no-op — no churn, honest counts
                        db.flush()
                        updates += 1
                        updated.add(obj.id)
                ids[c.index] = obj.id
        except IntegrityError as exc:
            _err(errors, c.index, _constraint_column(spec, exc), _integrity_message(exc))
            if not partial:
                db.rollback()
                return {"ok": False, "errors": errors, "summary": {"adds": 0, "updates": 0, "deletes": 0}, "ids": {}}

    deleted: list[int] = []
    if not blocked_deletes:
        for did in deletes:
            obj = db.get(spec.model, did)
            if obj is None:
                continue
            if spec.delete == "deactivate":
                obj.is_active = False
            elif spec.delete == "soft":
                obj.deleted_at = datetime.now(timezone.utc)
            else:  # hard
                db.delete(obj)
            removed += 1
            deleted.append(did)

    summary = {"adds": adds, "updates": updates, "deletes": removed}
    if adds or updates or removed:
        db.flush()
        _audit_changes(db, spec, actor_id, before, created, updated, deleted)
    try:
        db.commit()
    except IntegrityError as exc:  # e.g. a delete still referenced by a foreign key
        db.rollback()
        return {"ok": False, "errors": [{"row": None, "column": None, "message": _integrity_message(exc)}],
                "summary": {"adds": 0, "updates": 0, "deletes": 0}, "ids": {}}
    return {"ok": not errors, "errors": errors, "summary": summary, "ids": ids}


def _rows_by_id(db: Session, spec: TableSpec) -> dict[int, dict]:
    header, rows = _export_for(db, spec)
    return {int(r[0]): dict(zip(header, r)) for r in rows if r and str(r[0]).isdigit()}


def _row_cells(db: Session, spec: TableSpec, obj) -> dict:
    """One object in grid cell format, straight off the column declarations."""
    out = {}
    for c in spec.columns:
        value = getattr(obj, c.model_attr, None)
        if c.ref and value is not None and REFS[c.ref].value_attr != "id":
            target = db.get(REFS[c.ref].model, value)
            value = getattr(target, REFS[c.ref].value_attr) if target is not None else value
        out[c.name] = _cell(value)
    return out


def _editable(spec: TableSpec, row: dict) -> dict:
    return {c.name: row.get(c.name, "") for c in spec.columns if c.editable or c.name == "id"}


def _audit_changes(
    db: Session, spec: TableSpec, actor_id: int, before: dict[int, dict],
    created: set[int], updated: set[int], deleted: list[int],
) -> None:
    """One audit entry per touched row, in the grid's own cell format:
    updates carry {column: [old, new]}, creates and deletes the whole row (a
    delete's snapshot is what the recycle bin restores from)."""
    full = spec.full or spec  # snapshots keep every column, even ones this editor can't see
    after = _rows_by_id(db, spec) if (created or updated) else {}
    for rid in created | updated:
        if rid not in after:  # e.g. deactivated by this very edit — no longer exported
            obj = db.get(spec.model, rid)
            if obj is not None:
                after[rid] = _row_cells(db, full, obj)
    for rid in sorted(created):
        audit.log(db, actor_id, "bulk", "create", spec.key, rid, {"row": _editable(full, after.get(rid, {}))})
    for rid in sorted(updated):
        old, new = before.get(rid, {}), after.get(rid, {})
        changes = {
            c.name: [old.get(c.name, ""), new.get(c.name, "")]
            for c in spec.columns
            if c.editable and old.get(c.name, "") != new.get(c.name, "")
        }
        if changes:
            audit.log(db, actor_id, "bulk", "update", spec.key, rid, {"changes": changes})
    for rid in deleted:
        audit.log(db, actor_id, "bulk", "delete", spec.key, rid,
                  {"row": _editable(full, before.get(rid, {})), "policy": spec.delete})


def table_rows(db: Session, spec: TableSpec) -> list[dict]:
    """Rows as the grid gets them — only the spec's columns (a viewer's spec may
    have privileged columns removed; their values must not ride along)."""
    header, rows = _export_for(db, spec)
    keep = {c.name for c in spec.columns} if not spec.read_only else set(header)
    return [{k: v for k, v in zip(header, r) if k in keep} for r in rows]


def _integrity_message(exc: IntegrityError) -> str:
    text = str(exc.orig).lower()
    if "unique" in text or "duplicate" in text:
        return "This value is already used by another row (it must be unique)"
    if "foreign key" in text:
        return "Another record still points at this row"
    if "not null" in text or "null value" in text:
        return "A required value is missing"
    return "The database refused this row"


def _constraint_column(spec: TableSpec, exc: IntegrityError) -> str | None:
    """Best effort: name the grid column the failed constraint is about."""
    text = str(exc.orig)
    for c in spec.columns:
        if c.editable and (f".{c.model_attr}" in text or f"({c.model_attr})" in text):
            return c.name
    return None


def _insert_defaults(spec: TableSpec, fields: dict) -> dict:
    """Fill columns a new row needs but the grid never edits."""
    out = {**fields, **spec.insert_values}
    if spec.model is User:
        # bulk-created accounts get an unguessable password; they sign in only
        # after being explicitly linked (see auth.router), matching rebuild.
        out.setdefault("hashed_password", hash_password(secrets.token_urlsafe(24)))
    return out


# --- delete guards ----------------------------------------------------------
def _guard_position(db: Session, pid: int) -> str | None:
    if db.scalar(select(func.count()).select_from(Position).where(Position.parent_id == pid)):
        return f"cannot delete position {pid}: it still has child positions — reparent them first"
    if db.scalar(select(func.count()).select_from(PositionOccupant).where(PositionOccupant.position_id == pid)):
        return f"cannot delete position {pid}: it still has occupants — vacate the seat on the Org page first"
    return None


def _guard_event_kind(db: Session, kid: int) -> str | None:
    if db.scalar(select(func.count()).select_from(Event).where(Event.kind_id == kid)):
        return f"cannot delete event kind {kid}: events still use it"
    return None


def _guard_event(db: Session, eid: int) -> str | None:
    if db.scalar(select(func.count()).select_from(EventCategory).where(EventCategory.event_id == eid)):
        return f"cannot delete event {eid}: delete its categories first"
    return None


def _guard_event_category(db: Session, cid: int) -> str | None:
    if db.scalar(select(func.count()).select_from(EventTeam).where(EventTeam.category_id == cid)):
        return f"cannot delete category {cid}: delete its teams first"
    return None


def _references_to(db: Session, model: type, rid: int) -> list[str]:
    """Every (table, count) still pointing at row `rid` of `model` through a
    foreign key that would not cascade or null out on delete."""
    from app.core.database import Base

    target = model.__table__
    hits = []
    for table in Base.metadata.tables.values():
        for fk in table.foreign_keys:
            if fk.column.table is not target or (fk.ondelete or "").upper() in ("CASCADE", "SET NULL"):
                continue
            n = db.scalar(select(func.count()).select_from(table).where(fk.parent == rid))
            if n:
                hits.append(f"{n} {table.name.replace('_', ' ')}")
    return hits


def _guard_referenced(what: str):
    def guard(db: Session, rid: int, _what=what) -> str | None:
        spec_model = next(s.model for s in TABLES.values() if s.label == _what or s.key == _what)
        hits = _references_to(db, spec_model, rid)
        return f"cannot delete {_what} {rid}: still used by {', '.join(hits)}" if hits else None
    return guard


def _guard_member(db: Session, mid: int) -> str | None:
    from app.domains.finance.models import DuesPayment
    from app.domains.users.models import MemberProfile

    m = db.get(MemberProfile, mid)
    if m is not None and m.user_id is not None:
        return f"cannot delete member {mid}: they have a portal account — deactivate it on the People tab instead"
    if db.scalar(select(func.count()).select_from(DuesPayment).where(DuesPayment.member_id == mid)):
        return f"cannot delete member {mid}: they have dues payments on record"
    return None


for _key in ("finance_seasons", "finance_parties", "dues_tiers"):
    TABLES[_key].delete_guard = _guard_referenced(_key)
for _key in [k for k in TABLES if k.startswith("options_")]:
    TABLES[_key].delete_guard = _guard_referenced(_key)
TABLES["member_profiles"].delete_guard = _guard_member
TABLES["positions"].delete_guard = _guard_position
TABLES["event_kinds"].delete_guard = _guard_event_kind
TABLES["events"].delete_guard = _guard_event
TABLES["event_categories"].delete_guard = _guard_event_category


# --- Excel round-trip -------------------------------------------------------
# The guided importer: download a real .xlsx of (a scope of) a table, edit it
# freely in Excel / Sheets — formulas, fill-down, dropdowns — and upload it back.
# The upload is matched to the table's columns (by name or label, or a mapping
# the user picks), reference cells may hold labels, and a hidden copy of the
# exported values means only cells the user actually changed are written —
# a cell someone else changed in the portal since the download is a conflict,
# not an overwrite. Nothing is written until the user confirms the preview, and
# then all-or-nothing.
UPLOAD_MAX_ROWS = 5000
_META, _BASE, _LISTS = "_meta", "_base", "_lists"
STATUS_HEADER = "Status"


def _norm_header(text: str) -> str:
    import re

    return re.sub(r"[\s_\-]+", " ", str(text or "")).strip().lower()


def _xlsx_value(col: Column, cell: str, labels: dict[str, str]):
    """Grid string -> a typed Excel value (numbers stay numbers so formulas work)."""
    if cell == "":
        return None
    if col.ref or col.choices:
        return labels.get(cell, cell)
    try:
        if col.type == "int":
            return int(float(cell))
        if col.type == "number":
            return float(cell)
        if col.type == "bool":
            return cell == "true"
        if col.type == "date":
            return date.fromisoformat(cell[:10])
        if col.type == "datetime":
            return datetime.fromisoformat(cell)
    except ValueError:
        pass
    return cell


def _grid_value(col: Column, value) -> str:
    """An uploaded cell -> the grid's string convention for that column, so a
    file value compares equal to the exported one when the user didn't touch it."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        if col.type == "date" or (value.hour == value.minute == value.second == 0 and col.type != "datetime"):
            return value.date().isoformat()
        return value.replace(tzinfo=None).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, bool):
        return "true" if value else "false"
    text = str(value).strip()
    if col.type in ("int", "number") and not (col.ref or col.choices) and text:
        try:
            return _cell(float(text.replace(",", "")))
        except ValueError:
            return text
    if col.ref and text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]  # an id Excel turned into a float
    if col.type == "bool" and text:
        return "true" if text.lower() in ("true", "1", "yes", "y", "x", "✓") else "false" if text.lower() in (
            "false", "0", "no", "n", "") else text
    return text


def _label_maps(db: Session, spec: TableSpec) -> dict[str, tuple[dict[str, str], dict[str, str]]]:
    """col -> ({stored value: label}, {lowercased label: stored value}) for every pick column."""
    out = {}
    opts = _ref_options(db, spec)
    for c in spec.columns:
        if c.ref:
            pairs = [(str(o["value"]), str(o["label"])) for o in opts.get(c.name, [])]
        elif c.choices:
            pairs = [(v, v) for v in c.choices]
        else:
            continue
        out[c.name] = ({v: l for v, l in pairs}, {l.strip().lower(): v for v, l in pairs})
    return out


def _scoped_rows(db: Session, spec: TableSpec, scope: dict[str, str]) -> list[dict]:
    return [r for r in table_rows(db, spec) if all(str(r.get(k, "")) == str(v) for k, v in scope.items())]


def workbook_bytes(db: Session, spec: TableSpec, scope: dict[str, str] | None = None) -> bytes:
    import io
    import json

    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.datavalidation import DataValidation

    scope = {k: v for k, v in (scope or {}).items() if spec.column(k)}
    cols = spec.columns
    rows = _scoped_rows(db, spec, scope) if not spec.read_only else table_rows(db, spec)
    labels = _label_maps(db, spec) if not spec.read_only else {}

    wb = Workbook()
    ws = wb.active
    ws.title = spec.key[:31]  # Excel caps sheet names at 31 chars
    header = [c.header for c in cols] + ([STATUS_HEADER] if not spec.read_only else [])
    ws.append(header)
    for i, cell in enumerate(ws[1]):
        locked = i < len(cols) and not cols[i].editable
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="7F7F7F" if locked else "1F4E78")
    for r in rows:
        ws.append([_xlsx_value(c, r.get(c.name, ""), labels.get(c.name, ({}, {}))[0]) for c in cols])
    ws.freeze_panes = "B2"
    for i, c in enumerate(cols, start=1):
        longest = max([len(c.header)] + [len(str(r.get(c.name, ""))) for r in rows]) if rows else len(c.header)
        ws.column_dimensions[get_column_letter(i)].width = min(longest + 2, 48)

    if not spec.read_only:
        # dropdowns for every pick column, fed from a hidden list sheet
        lists = wb.create_sheet(_LISTS)
        lists.sheet_state = "hidden"
        last = max(len(rows) + 500, 1000)
        for j, c in enumerate([c for c in cols if c.name in labels and c.editable], start=1):
            values = list(labels[c.name][0].values())
            if not values:
                continue
            for k, v in enumerate(values, start=1):
                lists.cell(row=k, column=j, value=v)
            letter = get_column_letter(j)
            dv = DataValidation(type="list", formula1=f"={_LISTS}!${letter}$1:${letter}${len(values)}",
                                allow_blank=True, showErrorMessage=False)
            col_letter = get_column_letter(cols.index(c) + 1)
            dv.add(f"{col_letter}2:{col_letter}{last}")
            ws.add_data_validation(dv)
        # what was exported: which table and scope, and every value as it stood
        meta = wb.create_sheet(_META)
        meta.sheet_state = "hidden"
        meta.append(["table", spec.key])
        meta.append(["scope", json.dumps(scope)])
        meta.append(["exported_at", datetime.now(timezone.utc).isoformat()])
        base = wb.create_sheet(_BASE)
        base.sheet_state = "hidden"
        base.append([c.name for c in cols])
        for r in rows:
            base.append([r.get(c.name, "") for c in cols])

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@dataclass
class Upload:
    """A parsed upload: rows keyed by column name (only the columns the file
    has), each row's line in the sheet, and what the file says about itself."""

    rows: list[dict]
    lines: list[int]
    headers: list[str]
    matched: dict[str, str]  # file header -> column name
    unmatched: list[str]  # file headers matched to no column
    base: dict[int, dict] | None  # id -> exported grid values (our own template only)
    scope: dict[str, str]
    sheet: str | None


def parse_upload(content: bytes, filename: str, spec: TableSpec, mapping: dict[str, str] | None = None) -> Upload:
    """Read an uploaded .xlsx/.csv. Headers are matched to columns by name or
    label (case/spacing-insensitive), or by an explicit {header: column} mapping;
    unrecognised headers are reported and ignored. A missing column simply isn't
    touched on existing rows (and must not be required for new ones)."""
    import csv
    import io
    import json

    lower = filename.lower()
    base: dict[int, dict] | None = None
    scope: dict[str, str] = {}
    sheet_name = None
    if lower.endswith((".xlsx", ".xlsm")):
        import openpyxl

        try:
            wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True, read_only=True)
        except Exception as exc:  # corrupt / not really an xlsx
            raise ValueError("That file could not be opened as an Excel workbook.") from exc
        data_sheets = [n for n in wb.sheetnames if n not in (_META, _BASE, _LISTS)]
        sheet_name = spec.key[:31] if spec.key[:31] in data_sheets else data_sheets[0]
        grid = [list(row) for row in wb[sheet_name].iter_rows(values_only=True)]
        if _META in wb.sheetnames:
            meta = {str(r[0]): r[1] for r in wb[_META].iter_rows(values_only=True) if r and r[0]}
            if meta.get("table") == spec.key:
                try:
                    scope = {str(k): str(v) for k, v in json.loads(meta.get("scope") or "{}").items()}
                except ValueError:
                    scope = {}
                if _BASE in wb.sheetnames:
                    brows = [list(r) for r in wb[_BASE].iter_rows(values_only=True)]
                    if brows:
                        bh = [str(h) for h in brows[0]]
                        base = {}
                        for br in brows[1:]:
                            d = {h: ("" if v is None else str(v)) for h, v in zip(bh, br)}
                            if d.get("id", "").isdigit():
                                base[int(d["id"])] = d
    elif lower.endswith(".csv"):
        text = content.decode("utf-8-sig", errors="replace")
        grid = [list(row) for row in csv.reader(io.StringIO(text))]
    else:
        raise ValueError("Unsupported file — upload a .xlsx or .csv file.")

    by_key: dict[str, str] = {}
    for c in spec.columns:
        by_key.setdefault(_norm_header(c.name), c.name)
        by_key.setdefault(_norm_header(c.header), c.name)
    mapping = {k: v for k, v in (mapping or {}).items() if v == "" or spec.column(v)}

    def match(h: str) -> str | None:
        if h in mapping:
            return mapping[h] or None  # "" = deliberately ignored
        return by_key.get(_norm_header(h))

    # the header row: the first of the top 25 rows matching the most columns
    best, header_idx = 0, None
    for i, row in enumerate(grid[:25]):
        n = sum(1 for h in row if h is not None and str(h).strip() and match(str(h).strip()))
        if n > best:
            best, header_idx = n, i
    if header_idx is None:
        header_idx = next((i for i, row in enumerate(grid[:25]) if sum(1 for h in row if h not in (None, "")) >= 2), None)
    if header_idx is None:
        raise ValueError("Could not find a header row — keep the first row of column names.")
    headers = ["" if h is None else str(h).strip() for h in grid[header_idx]]

    matched: dict[str, str] = {}
    unmatched: list[str] = []
    idx: dict[str, int] = {}
    for j, h in enumerate(headers):
        if not h or _norm_header(h) == _norm_header(STATUS_HEADER):
            continue
        name = match(h)
        if name and name not in idx:
            col = spec.column(name)
            if col and (col.editable or name == "id"):
                idx[name] = j
                matched[h] = name
            continue
        if h not in mapping:
            unmatched.append(h)

    rows: list[dict] = []
    lines: list[int] = []
    for k, raw in enumerate(grid[header_idx + 1:], start=header_idx + 2):
        if not any(v not in (None, "") and str(v).strip() for v in raw):
            continue  # skip fully blank lines
        row = {}
        for name, j in idx.items():
            col = spec.column(name)
            row[name] = _grid_value(col, raw[j] if j < len(raw) else None)
        row.setdefault("id", "")
        rows.append(row)
        lines.append(k)
        if len(rows) > UPLOAD_MAX_ROWS:
            raise ValueError(f"The file has more than {UPLOAD_MAX_ROWS} rows — split it into smaller files.")
    return Upload(rows=rows, lines=lines, headers=headers, matched=matched, unmatched=unmatched,
                  base=base, scope=scope, sheet=sheet_name)


def prepare_upload(db: Session, spec: TableSpec, up: Upload, fixed: dict[str, str]) -> list[dict]:
    """Turn parsed file rows into engine rows: pick labels -> stored values,
    scope values filled into new rows, and — for our own exported template —
    unchanged cells dropped and changed ones sent with their exported value as
    the conflict base."""
    labels = _label_maps(db, spec)
    scope = {**up.scope, **fixed}
    out = []
    for row in up.rows:
        r = dict(row)
        for name, (_, by_label) in labels.items():
            v = r.get(name)
            if v:
                hit = by_label.get(v.strip().lower())
                if hit is not None:
                    r[name] = hit
        rid = r.get("id", "")
        if rid and up.base is not None and rid.isdigit() and int(rid) in up.base:
            exported = up.base[int(rid)]
            changed = {k: v for k, v in r.items() if k != "id" and v != exported.get(k, "")}
            r = {"id": rid, **changed, "_base": {k: exported.get(k, "") for k in changed}}
        elif not rid:
            for k, v in scope.items():
                if spec.column(k) and not r.get(k):
                    r[k] = v
        out.append(r)
    return out


def plan_upload(db: Session, spec: TableSpec, rows: list[dict], delete_missing: bool,
                scope: dict[str, str] | None = None) -> dict:
    """Diff the uploaded rows against the DB without writing. Returns the counts
    the confirm dialog shows, the ids that would be deleted, and any errors.
    Deletion candidates are limited to the file's scope (e.g. its season): a
    one-season sheet never proposes deleting other seasons' rows."""
    coerced, errors, _ = validate(db, spec, rows, [])
    scope = {k: v for k, v in (scope or {}).items() if spec.column(k)}
    in_scope = {int(r["id"]) for r in _scoped_rows(db, spec, scope)}
    uploaded_ids = {int(r["id"]) for r in rows if str(r.get("id", "")).isdigit()}

    new = changed = unchanged = 0
    for c in coerced:
        if c.id is None:
            new += 1
            continue
        obj = db.get(spec.model, c.id)
        if obj is not None and any(getattr(obj, a) != v for a, v in c.fields.items()):
            changed += 1
        else:
            unchanged += 1

    can_delete = not (spec.append_only or spec.delete == "none")
    missing_ids = sorted(in_scope - uploaded_ids) if can_delete else []
    return {
        "ok": not errors,
        "errors": errors,
        "new": new,
        "changed": changed,
        "unchanged": unchanged,
        "missing_ids": missing_ids,
        "can_delete": can_delete,
        "will_delete": len(missing_ids) if delete_missing else 0,
    }


def annotated_workbook(content: bytes, filename: str, up: Upload, errors: list[dict]) -> bytes:
    """The user's own file handed back with the Status column filled in: ✓ or
    what is wrong on that line — fix the marked rows and upload again."""
    import io

    import openpyxl

    by_line: dict[int, list[str]] = {}
    general: list[str] = []
    for e in errors:
        msg = (f"{e['column']}: " if e.get("column") else "") + e["message"]
        if e.get("row") is not None and e["row"] < len(up.lines):
            by_line.setdefault(up.lines[e["row"]], []).append(msg)
        else:
            general.append(msg)

    if filename.lower().endswith((".xlsx", ".xlsm")):
        wb = openpyxl.load_workbook(io.BytesIO(content))  # keeps the user's formulas
        ws = wb[up.sheet] if up.sheet in wb.sheetnames else wb.active
    else:
        import csv

        wb = openpyxl.Workbook()
        ws = wb.active
        for row in csv.reader(io.StringIO(content.decode("utf-8-sig", errors="replace"))):
            ws.append(row)
    from openpyxl.styles import Font, PatternFill

    header_row = (up.lines[0] - 1) if up.lines else 1
    status_col = next((j for j, h in enumerate(up.headers, start=1) if _norm_header(h) == _norm_header(STATUS_HEADER)),
                      len(up.headers) + 1)
    ws.cell(row=header_row, column=status_col, value=STATUS_HEADER).font = Font(bold=True)
    bad = PatternFill("solid", fgColor="F8D7DA")
    for line in up.lines:
        msgs = by_line.get(line)
        cell = ws.cell(row=line, column=status_col, value="; ".join(msgs) if msgs else "✓")
        if msgs:
            cell.fill = bad
    if general:
        ws.cell(row=max(header_row - 1, 1), column=status_col, value="; ".join(general)).fill = bad
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _cell_to_str(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


# --- history / recycle bin ----------------------------------------------------
def _entry(e, names: dict[int, str], spec: TableSpec | None = None) -> dict:
    import json

    try:
        detail = json.loads(e.detail or "{}")
    except ValueError:
        detail = {}
    if spec is not None:  # only the columns this viewer may see
        shown = {c.name for c in spec.columns}
        for k in ("row", "changes"):
            if isinstance(detail.get(k), dict):
                detail[k] = {c: v for c, v in detail[k].items() if c in shown}
    return {
        "id": e.id, "action": e.action, "entity_id": e.entity_id, "detail": detail,
        "actor": names.get(e.actor_id) if e.actor_id else None,
        "at": e.created_at.isoformat() if e.created_at else None,
    }


def _actor_names(db: Session, entries) -> dict[int, str]:
    ids = {e.actor_id for e in entries if e.actor_id}
    if not ids:
        return {}
    return {u.id: u.full_name for u in db.scalars(select(User).where(User.id.in_(ids)))}


def row_history(db: Session, spec: TableSpec, rid: int) -> list[dict]:
    """Every grid edit to one row, newest first."""
    from app.domains.audit.models import AuditLog

    entries = list(db.scalars(
        select(AuditLog)
        .where(AuditLog.domain == "bulk", AuditLog.entity_type == spec.key, AuditLog.entity_id == rid)
        .order_by(AuditLog.id.desc())
    ))
    names = _actor_names(db, entries)
    return [h for h in (_entry(e, names, spec) for e in entries)
            if h["action"] != "update" or h["detail"].get("changes")]


def trash(db: Session, spec: TableSpec, limit: int = 200) -> list[dict]:
    """Deleted rows that haven't been restored since, newest first."""
    from app.domains.audit.models import AuditLog

    base = select(AuditLog).where(AuditLog.domain == "bulk", AuditLog.entity_type == spec.key)
    restored = {
        _entry(e, {})["detail"].get("audit_id")
        for e in db.scalars(base.where(AuditLog.action == "restore"))
    }
    entries = [
        e for e in db.scalars(base.where(AuditLog.action == "delete").order_by(AuditLog.id.desc()).limit(limit))
        if e.id not in restored
    ]
    names = _actor_names(db, entries)
    return [_entry(e, names, spec) for e in entries]


def restore(db: Session, spec: TableSpec, audit_id: int, actor_id: int) -> dict:
    """Bring a deleted row back from its recycle-bin snapshot. A hard-deleted
    row is re-inserted under its old id after re-validating the snapshot (a
    record it pointed at may be gone since); a soft-deleted or deactivated row
    just has the flag flipped back."""
    from app.domains.audit.models import AuditLog

    entry = db.get(AuditLog, audit_id)
    if entry is None or entry.domain != "bulk" or entry.entity_type != spec.key or entry.action != "delete":
        return {"ok": False, "message": "That deleted row is not in this table's recycle bin."}
    if audit_id not in {t["id"] for t in trash(db, spec, limit=10_000)}:
        return {"ok": False, "message": "That row was already restored."}
    rid = entry.entity_id
    detail = _entry(entry, {})["detail"]
    spec = spec.full or spec  # the snapshot holds every column; restore all of them
    obj = db.get(spec.model, rid)

    if spec.delete in ("soft", "deactivate"):
        if obj is None:
            return {"ok": False, "message": "The row no longer exists in the database."}
        if spec.delete == "soft":
            obj.deleted_at = None
        else:
            obj.is_active = True
    else:
        if obj is not None:
            return {"ok": False, "message": f"A row with id {rid} already exists."}
        snapshot = {k: v for k, v in (detail.get("row") or {}).items() if k != "id"}
        coerced, errors, _ = validate(db, spec, [{**snapshot, "id": ""}], [])
        if errors or not coerced:
            msg = errors[0]["message"] if errors else "The snapshot could not be read."
            return {"ok": False, "message": f"Can't restore: {msg}"}
        try:
            with db.begin_nested():
                db.add(spec.model(id=rid, **_insert_defaults(spec, coerced[0].fields)))
                db.flush()
        except IntegrityError as exc:
            db.rollback()
            return {"ok": False, "message": f"Can't restore: {_integrity_message(exc)}"}
    audit.log(db, actor_id, "bulk", "restore", spec.key, rid, {"audit_id": audit_id})
    db.commit()
    return {"ok": True, "id": rid}
