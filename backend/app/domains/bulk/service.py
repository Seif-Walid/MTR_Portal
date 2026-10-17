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
    header, rows = _export_for(db, spec)
    columns = [_column_payload(c) for c in spec.columns]
    row_dicts = [dict(zip(header, r)) for r in rows]
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
    }


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
    after = _rows_by_id(db, spec) if (created or updated) else {}
    for rid in created | updated:
        if rid not in after:  # e.g. deactivated by this very edit — no longer exported
            obj = db.get(spec.model, rid)
            if obj is not None:
                after[rid] = _row_cells(db, spec, obj)
    for rid in sorted(created):
        audit.log(db, actor_id, "bulk", "create", spec.key, rid, {"row": _editable(spec, after.get(rid, {}))})
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
                  {"row": _editable(spec, before.get(rid, {})), "policy": spec.delete})


def table_rows(db: Session, spec: TableSpec) -> list[dict]:
    header, rows = _export_for(db, spec)
    return [dict(zip(header, r)) for r in rows]


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
# The whole workflow: download a real .xlsx of a table, edit it freely in Excel,
# upload it back. We diff the file against the DB and apply
# adds/updates (and, opt-in, delete rows the user removed from the sheet).
def workbook_bytes(db: Session, spec: TableSpec) -> bytes:
    import io

    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter

    header = [c.name for c in spec.columns]
    _, rows = _export_for(db, spec)

    wb = Workbook()
    ws = wb.active
    ws.title = spec.key[:31]  # Excel caps sheet names at 31 chars
    ws.append(header)
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F4E78")
    for r in rows:
        ws.append(r)
    ws.freeze_panes = "A2"
    for i, name in enumerate(header, start=1):
        longest = max([len(name)] + [len(str(r[i - 1])) for r in rows]) if rows else len(name)
        ws.column_dimensions[get_column_letter(i)].width = min(longest + 2, 48)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def parse_upload(content: bytes, filename: str, spec: TableSpec) -> list[dict]:
    """Read an uploaded .xlsx/.csv into row dicts keyed by this table's columns.
    The file must keep every column from the downloaded template (so an update
    never silently blanks a column that was dropped from the sheet)."""
    import csv
    import io

    lower = filename.lower()
    if lower.endswith((".xlsx", ".xlsm")):
        import openpyxl

        wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True, read_only=True)
        ws = wb[spec.key] if spec.key in wb.sheetnames else wb[wb.sheetnames[0]]
        grid = [[_cell_to_str(c) for c in row] for row in ws.iter_rows(values_only=True)]
    elif lower.endswith(".csv"):
        text = content.decode("utf-8-sig", errors="replace")
        grid = [[c.strip() for c in row] for row in csv.reader(io.StringIO(text))]
    else:
        raise ValueError("Unsupported file — upload a .xlsx or .csv file.")

    # find the header row (the first one containing 'id')
    header_idx = next((i for i, row in enumerate(grid[:25]) if "id" in [c.strip() for c in row]), None)
    if header_idx is None:
        raise ValueError("Could not find the header row — keep the first row of column names.")
    header = [c.strip() for c in grid[header_idx]]
    expected = [c.name for c in spec.columns]
    missing = [c for c in expected if c not in header]
    if missing:
        raise ValueError(f"The sheet is missing column(s): {', '.join(missing)}. Keep every column.")
    idx = {name: header.index(name) for name in expected}

    rows: list[dict] = []
    for raw in grid[header_idx + 1 :]:
        if not any(c.strip() for c in raw):
            continue  # skip fully blank lines
        rows.append({name: (raw[idx[name]] if idx[name] < len(raw) else "") for name in expected})
    return rows


def _cell_to_str(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def plan_upload(db: Session, spec: TableSpec, rows: list[dict], delete_missing: bool) -> dict:
    """Diff the uploaded rows against the DB without writing. Returns the counts
    the confirm dialog shows, the ids that would be deleted, and any errors."""
    coerced, errors, _ = validate(db, spec, rows, [])
    existing_ids = _spec_ids(db, spec)
    uploaded_ids = {c.id for c in coerced if c.id is not None}

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

    # rows in the DB but absent from the uploaded file — candidate deletions
    can_delete = not (spec.append_only or spec.delete == "none")
    missing_ids = sorted(existing_ids - uploaded_ids) if can_delete else []
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


# --- history / recycle bin ----------------------------------------------------
def _entry(e, names: dict[int, str]) -> dict:
    import json

    try:
        detail = json.loads(e.detail or "{}")
    except ValueError:
        detail = {}
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
    return [_entry(e, names) for e in entries]


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
    return [_entry(e, names) for e in entries]


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
