"""Automatic audit trail: every row a signed-in person creates, changes or
deletes is recorded, whether or not the route that did it writes an audit
entry of its own.

Routes used to opt in by calling audit.service.log(); most never did (time
blocks, calendar, requests, ...), so the log showed only a fraction of what
people actually did. This hooks the ORM session instead:

- get_current_user marks the session with the acting person (ACTOR).
- after_flush collects each inserted / updated / deleted row, with the fields
  that changed, while the ORM still knows the before-values.
- before_commit turns them into AuditLog rows in the same transaction — unless
  the route already wrote its own (richer) entry in this transaction, in which
  case that entry stands for the change and the raw rows are skipped.

Changes made with no person behind them (seed, scripts, background jobs) are
not recorded here, and neither are bookkeeping tables (sessions,
notifications, the AI's chat history, the audit logs themselves). Bulk Core
statements (session.execute(update/delete(...))) bypass the ORM and are not
seen; routes that use them log explicitly."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

from app.domains.audit.models import AuditLog
from app.domains.audit.service import AI_STAMP, EXPLICIT

ACTOR = "audit_actor_id"
PENDING = "audit_auto_pending"

# tables whose rows are bookkeeping, not anyone's change worth auditing
SKIP_TABLES = {
    "audit_log",
    "org_audit_log",
    "auth_sessions",
    "password_reset_tokens",
    "notifications",
    "ai_conversations",
    "ai_messages",
    "ai_embeddings",
    "ai_files",
    "ai_pending_actions",  # confirmed actions get their own explicit entry
    "oauth_codes",
    "push_subscriptions",  # device registrations, not data anyone edits
    "push_keys",  # holds the server's private signing key
}
# columns that change as a side effect, never by intent
SKIP_COLUMNS = {"updated_at", "created_at", "last_login", "last_login_at", "last_seen_at", "last_used_at"}
# never copy secrets into the log
SECRET_WORDS = ("password", "token", "secret", "hash", "credential")
# columns that name a row for a human reading the log
LABEL_COLUMNS = ("name", "title", "full_name", "label", "summary", "description", "path")

_MAX_TEXT = 200


def _domain(obj) -> str:
    parts = type(obj).__module__.split(".")
    if len(parts) > 2 and parts[1] == "domains":
        return parts[2]
    return "portal"


def _entity(table: str) -> str:
    if table.endswith("ies"):
        return table[:-3] + "y"
    if table.endswith("ses") or table.endswith("xes"):
        return table[:-2]
    if table.endswith("s") and not table.endswith("ss"):
        return table[:-1]
    return table


def _plain(value):
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return f"<{len(value)} bytes>"
    text = str(value)
    return text if len(text) <= _MAX_TEXT else text[:_MAX_TEXT] + "…"


def _secret(key: str) -> bool:
    k = key.lower()
    return any(w in k for w in SECRET_WORDS)


def _columns(obj):
    for attr in inspect(obj).mapper.column_attrs:
        key = attr.key
        if key in SKIP_COLUMNS or key == "id":
            continue
        yield key


def _snapshot(obj) -> dict:
    """Every set column of a row (created / deleted), secrets masked."""
    out = {}
    for key in _columns(obj):
        value = getattr(obj, key, None)
        if value is None or value == "":
            continue
        out[key] = "•••" if _secret(key) else _plain(value)
    return out


def _changes(obj) -> dict:
    """{column: [before, after]} for the columns this flush changed."""
    state = inspect(obj)
    out = {}
    for key in _columns(obj):
        hist = state.attrs[key].history
        if not hist.has_changes():
            continue
        before = hist.deleted[0] if hist.deleted else None
        after = hist.added[0] if hist.added else None
        if before == after:
            continue
        out[key] = ["•••", "•••"] if _secret(key) else [_plain(before), _plain(after)]
    return out


def _label(obj) -> str | None:
    for key in LABEL_COLUMNS:
        value = getattr(obj, key, None)
        if isinstance(value, str) and value.strip():
            return _plain(value.strip())
    return None


def _ident(obj) -> int | None:
    pk = inspect(obj).mapper.primary_key_from_instance(obj)
    if pk and len(pk) == 1 and isinstance(pk[0], int):
        return pk[0]
    return None


@event.listens_for(Session, "after_flush")
def _collect(session: Session, _ctx) -> None:
    actor = session.info.get(ACTOR)
    if actor is None:
        return
    pending = session.info.setdefault(PENDING, [])
    stamp = session.info.get(AI_STAMP)
    for verb, objs in (("created", session.new), ("updated", session.dirty), ("deleted", session.deleted)):
        for obj in objs:
            table = getattr(obj, "__tablename__", None)
            if not table or table in SKIP_TABLES or isinstance(obj, AuditLog):
                continue
            if verb == "updated":
                if not session.is_modified(obj, include_collections=False):
                    continue
                detail = _changes(obj)
                if not detail:
                    continue
                detail = {"changes": detail}
            else:
                detail = {"values": _snapshot(obj)}
            label = _label(obj)
            if label:
                detail = {"name": label, **detail}
            pending.append({
                "actor_id": actor,
                "domain": _domain(obj),
                "action": verb,
                "entity_type": _entity(table),
                "entity_id": _ident(obj),
                "detail": detail,
                "stamp": dict(stamp) if stamp else None,
            })


@event.listens_for(Session, "before_commit")
def _write(session: Session) -> None:
    if session.info.get(ACTOR) is None:
        return
    session.flush()  # catch anything not yet flushed
    pending = session.info.pop(PENDING, [])
    if not pending or session.info.get(EXPLICIT):
        return  # nothing changed, or the route recorded the change itself
    import json

    for p in pending:
        entry = AuditLog(
            actor_id=p["actor_id"],
            domain=p["domain"],
            action=p["action"],
            entity_type=p["entity_type"],
            entity_id=p["entity_id"],
            detail=json.dumps(p["detail"], default=str),
        )
        if p["stamp"]:
            entry.via = p["stamp"]["via"]
            entry.approved_by_id = p["stamp"]["approved_by_id"]
            entry.ai_action_id = p["stamp"]["action_id"]
        session.add(entry)


@event.listens_for(Session, "after_commit")
@event.listens_for(Session, "after_rollback")
def _reset(session: Session) -> None:
    session.info.pop(PENDING, None)
    session.info.pop(EXPLICIT, None)
