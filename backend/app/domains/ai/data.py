"""Read-only SQL over the portal's data, as one user may see it.

The assistant can answer anything the data supports — joins, counts,
filters — without a dedicated tool per question. Each query runs against a
throw-away in-memory SQLite built only from the tables it names, each one:
- gated by the same privilege the Data editor uses for that table,
- narrowed to the columns this user may see (privileged columns dropped),
- stripped of secrets (password / token / hash columns, secret tables),
- filtered like the editor (soft-deleted rows hidden).
The connection is query-only, so nothing can be written anywhere.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum

from fastapi import HTTPException, status
from sqlalchemy import LargeBinary, select
from sqlalchemy.orm import Session

from app.domains.access import service as access
from app.domains.users.models import User

ROW_CAP = 20_000  # per table copied into the query DB
NEVER = {
    "ai_tokens", "ai_embeddings", "ai_messages", "ai_conversations", "ai_pending_actions", "ai_files",
    "auth_sessions", "password_reset_tokens", "drive_connections",
}
SECRET = re.compile(r"(password|token|secret|hash)", re.I)
# structural columns a curated table may not list but that joins need
STRUCTURAL = {"id", "entity_type", "entity_id", "role_template_id", "created_at", "updated_at"}


@dataclass
class Source:
    name: str
    description: str
    model: type | None
    columns: list[str]
    filters: list
    rows: Callable[[Session], list[tuple]] | None = None  # derived views


def _people_directory(db: Session, user: User) -> Source | None:
    """Names for anyone who may view people, even without users.manage."""
    if not access.has_privilege(db, user, "people.view"):
        return None
    return Source("user_names", "Every account's id, name, department and active flag — join on user ids.",
                  User, ["id", "full_name", "department", "mtr_id", "is_active"], [])


def _event_list_rows(db: Session) -> list[tuple]:
    from app.domains.events.models import Event, EventKind
    from app.domains.positions.models import Position, PositionOccupant

    kinds = {k.id: k.name for k in db.scalars(select(EventKind))}
    events = list(db.scalars(select(Event)))
    names = {u.id: u.full_name for u in db.scalars(select(User))}
    managers: dict[int, list[str]] = {}
    for eid, title, uid in db.execute(
            select(Position.entity_id, Position.title, PositionOccupant.user_id)
            .join(PositionOccupant, PositionOccupant.position_id == Position.id)
            .where(Position.entity_type == "event")):
        managers.setdefault(eid, []).append(f"{names.get(uid)} ({title})")
    return [(e.id, e.name, e.full_name, kinds.get(e.kind_id), _plain(e.status), _plain(e.start_date),
             _plain(e.end_date), e.location, e.result, _plain(e.awards), "; ".join(managers.get(e.id, [])) or None)
            for e in events]


def _strip_owner(title: str, owner: str) -> str:
    if title.lower().startswith(owner.lower() + " ") and len(title) > len(owner) + 1:
        rest = title[len(owner) + 1:]
        return rest[:1].upper() + rest[1:]
    return title


def _event_people_rows(db: Session) -> list[tuple]:
    """Everyone on every team: the member list plus role-seat holders, one row
    per person per team (roles merged) — how the portal itself shows a team."""
    from app.domains.events.models import Event, EventCategory, EventTeam, EventTeamMember
    from app.domains.positions.models import Position, PositionOccupant

    users = {u.id: u.full_name for u in db.scalars(select(User))}
    teams = {t.id: t for t in db.scalars(select(EventTeam).where(EventTeam.deleted_at.is_(None)))}
    cats = {c.id: c for c in db.scalars(select(EventCategory))}
    events = {e.id: e for e in db.scalars(select(Event))}
    rows: dict[tuple[int, int | None, int], list] = {}

    def add(event_id, team_id, user_id, role, source):
        key = (event_id, team_id, user_id)
        if key not in rows:
            rows[key] = [set(), set()]
        if role:
            rows[key][0].add(role)
        rows[key][1].add(source)

    for m in db.scalars(select(EventTeamMember)):
        t = teams.get(m.team_id)
        if t and t.category_id in cats:
            add(cats[t.category_id].event_id, t.id, m.user_id, m.role, "member")
    seats = db.execute(select(Position.entity_type, Position.entity_id, Position.title, PositionOccupant.user_id)
                       .join(PositionOccupant, PositionOccupant.position_id == Position.id)
                       .where(Position.entity_type.in_(("event", "team"))))
    for etype, eid, title, uid in seats:
        if etype == "team" and eid in teams and teams[eid].category_id in cats:
            add(cats[teams[eid].category_id].event_id, eid, uid, _strip_owner(title, teams[eid].name), "seat")
    staffed = {team_id for (_, team_id, _) in rows}
    for t in teams.values():  # empty teams still count as teams
        if t.id not in staffed and t.category_id in cats:
            rows[(cats[t.category_id].event_id, t.id, None)] = [set(), set()]
    out = []
    for (event_id, team_id, uid), (roles, srcs) in rows.items():
        t = teams.get(team_id) if team_id else None
        parent = teams.get(t.parent_team_id) if t and t.parent_team_id else None
        ev = events.get(event_id)
        out.append((event_id, ev.name if ev else None, team_id, t.name if t else None,
                    parent.name if parent else None, cats[t.category_id].name if t else None,
                    uid, users.get(uid) if uid else None, " · ".join(sorted(roles)) or None, "+".join(sorted(srcs)) or None))
    return out


VIEWS = [
    ("event_list", "events.view",
     "Every event with its kind name (Competition / Training / R&D …), status ('archived' = past), dates, location, result, awards, and managers (event-level seats such as the PM — they are not team members).",
     ["event_id", "name", "full_name", "kind", "status", "start_date", "end_date", "location", "result", "awards", "managers"],
     _event_list_rows),
    ("event_people", "events.view",
     "Everyone on every event team — member list AND role-seat holders (coach, lead, member seats) in one place, one row per person per team; a team with nobody on it has one row with user_id NULL (so COUNT(DISTINCT team_id) counts every team and COUNT(DISTINCT user_id) counts people). Event-level seats (the PM …) are not here — see event_list.managers. parent_team = the team this sub-team sits in. Use this for any 'who is on which team' or member count.",
     ["event_id", "event_name", "team_id", "team_name", "parent_team", "category", "user_id", "full_name", "role", "source"],
     _event_people_rows),
]


def sources(db: Session, user: User) -> dict[str, Source]:
    from app.domains.bulk.registry import TABLES, ensure_all_tables_registered

    ensure_all_tables_registered()
    privs = access.privileges_for(db, user)
    out: dict[str, Source] = {}
    for key, spec in TABLES.items():
        if key in NEVER or not access.has_privilege(db, user, spec.privilege):
            continue
        table = spec.model.__table__
        db_cols = [c for c in table.columns if not isinstance(c.type, LargeBinary) and not SECRET.search(c.name)]
        if spec.read_only:
            cols = [c.name for c in db_cols]
        else:
            seen = spec.for_privileges(privs)
            attr_to_col = {a.key: a.columns[0].name for a in spec.model.__mapper__.column_attrs}
            allowed = {attr_to_col.get(c.model_attr, c.model_attr) for c in seen.columns} | STRUCTURAL
            cols = [c.name for c in db_cols if c.name in allowed]
        out[key] = Source(key, spec.description or spec.label, spec.model, cols, spec.filters())
    for name, privilege, about, cols, fn in VIEWS:
        if access.has_privilege(db, user, privilege):
            out[name] = Source(name, about, None, cols, [], fn)
    extra = _people_directory(db, user)
    if extra:
        out[extra.name] = extra
    return out


def schema(db: Session, user: User) -> list[dict]:
    return [{"table": s.name, "about": s.description, "columns": s.columns} for s in sources(db, user).values()]


def _plain(v):
    if v is None or isinstance(v, (int, float, str)):
        return v
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, Enum):
        return v.value
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (list, dict)):
        return json.dumps(v, ensure_ascii=False)
    return str(v)


def _referenced(sql_texts: list[str], available: dict[str, Source]) -> list[Source]:
    words = {w.lower() for text in sql_texts for w in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", text)}
    return [s for name, s in available.items() if name in words]


def connect(db: Session, user: User, sql_texts: list[str]) -> sqlite3.Connection:
    """In-memory DB holding exactly the visible tables the queries mention."""
    available = sources(db, user)
    conn = sqlite3.connect(":memory:")
    for src in _referenced(sql_texts, available):
        if src.rows is not None:
            rows = src.rows(db)[:ROW_CAP]
        else:
            table = src.model.__table__
            cols = [table.c[name] for name in src.columns]
            q = select(*cols).select_from(src.model).where(*src.filters).limit(ROW_CAP)
            rows = db.execute(q).all()
        quoted = ", ".join(f'"{c}"' for c in src.columns)
        conn.execute(f'CREATE TABLE "{src.name}" ({quoted})')
        conn.executemany(f'INSERT INTO "{src.name}" VALUES ({", ".join("?" * len(src.columns))})',
                         [[_plain(v) for v in r] for r in rows])
    conn.execute("PRAGMA query_only = ON")
    return conn


def run(conn: sqlite3.Connection, sql: str, params: dict | None = None, limit: int = 500) -> dict:
    stripped = sql.strip().rstrip(";")
    if not re.match(r"(?is)^\s*(select|with)\b", stripped) or ";" in stripped:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Only a single SELECT (or WITH … SELECT) query is allowed")
    try:
        cur = conn.execute(stripped, params or {})
    except sqlite3.Error as exc:
        hint = ""
        if "no such table" in str(exc):
            hint = " — call data_schema for the tables you may query"
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"SQL error: {exc}{hint}") from exc
    columns = [d[0] for d in cur.description or []]
    rows = cur.fetchmany(limit + 1)
    return {"columns": columns, "rows": [list(r) for r in rows[:limit]], "truncated": len(rows) > limit}


def query(db: Session, user: User, sql: str, limit: int = 200) -> dict:
    conn = connect(db, user, [sql])
    try:
        return run(conn, sql, limit=limit)
    finally:
        conn.close()
