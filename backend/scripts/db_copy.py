"""Copy every business table from one database into another, faithfully.

Built for the one-off "initial push": the real dataset lives in the local dev
SQLite (``portal_dev.db``); production runs the identical schema on Postgres but
is empty. This copies the SQLite rows into Postgres so the two hold the same
data, ids and all.

Why not a JSON dump + reload? Because reading and writing through the *same*
typed SQLAlchemy ``Table`` objects lets SQLAlchemy's result-processors (SQLite
-> Python) and bind-processors (Python -> Postgres) handle every column type —
booleans stored as 0/1, enums, dates, JSON — with no hand-rolled coercion to
get subtly wrong.

Preconditions (asserted at runtime):
  * both databases are at the *same* Alembic head (identical schema), and
  * ``alembic_version`` itself is never copied (each side manages its own).

Foreign keys — including the self-referential ``users.manager_id`` /
``positions.parent_id`` and mutual task<->request links — are handled by turning
off FK enforcement for the load (``session_replication_role = replica`` on
Postgres; ``PRAGMA foreign_keys=OFF`` on SQLite) rather than by trying to find a
perfect insert order, then Postgres sequences are re-synced to ``max(id)``.

Usage (from backend/):
    # dry run: report what WOULD be copied, touch nothing
    DATABASE_URL=postgresql+psycopg://portal:portal@db:5432/portal \\
        python -m scripts.db_copy --source sqlite:////data/portal_dev.db

    # do it: wipe the target's business tables first, then copy
    DATABASE_URL=postgresql+psycopg://portal:portal@db:5432/portal \\
        python -m scripts.db_copy --source sqlite:////data/portal_dev.db --wipe --commit

The target is taken from DATABASE_URL (the app's own setting) unless --target is
given. --wipe without --commit is still a dry run.
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import Engine

from app.core.database import Base

# Import every model module so Base.metadata is complete (same list app.seed uses).
from app.domains.access import models as _access_models  # noqa: F401
from app.domains.audit import models as _audit_models  # noqa: F401
from app.domains.auth import models as _auth_models  # noqa: F401
from app.domains.events import models as _comp_models  # noqa: F401
from app.domains.inventory import models as _inv_models  # noqa: F401
from app.domains.notifications import models as _notif_models  # noqa: F401
from app.domains.positions import models as _pos_models  # noqa: F401
from app.domains.requests import models as _req_models  # noqa: F401
from app.domains.sync import models as _sync_models  # noqa: F401
from app.domains.tasks import models as _task_models  # noqa: F401
from app.domains.users import models as _user_models  # noqa: F401

# Alembic's bookkeeping table is not part of Base.metadata, but guard anyway.
SKIP_TABLES = {"alembic_version"}

BATCH = 500


def sorted_business_tables():
    """FK-safe order (parents first); alembic_version excluded."""
    return [t for t in Base.metadata.sorted_tables if t.name not in SKIP_TABLES]


def _fk_off(conn) -> None:
    if conn.dialect.name == "postgresql":
        conn.execute(text("SET session_replication_role = 'replica'"))
    elif conn.dialect.name == "sqlite":
        conn.execute(text("PRAGMA foreign_keys=OFF"))


def _fk_on(conn) -> None:
    if conn.dialect.name == "postgresql":
        conn.execute(text("SET session_replication_role = 'origin'"))
    elif conn.dialect.name == "sqlite":
        conn.execute(text("PRAGMA foreign_keys=ON"))


def _resync_sequences(conn, tables) -> None:
    """After inserting explicit integer ids, Postgres' identity sequences still
    point at 1 — the next natural insert would collide. Fast-forward each to
    max(id). No-op on SQLite (rowid handles it)."""
    if conn.dialect.name != "postgresql":
        return
    for table in tables:
        pk = list(table.primary_key.columns)
        if len(pk) != 1 or not isinstance(pk[0].type.python_type, type) or pk[0].type.python_type is not int:
            continue
        col = pk[0].name
        conn.execute(
            text(
                "SELECT setval(pg_get_serial_sequence(:tbl, :col), "
                "COALESCE((SELECT MAX(\"%s\") FROM \"%s\"), 1), "
                "(SELECT COUNT(*) FROM \"%s\") > 0)" % (col, table.name, table.name)
            ),
            {"tbl": table.name, "col": col},
        )


def _assert_same_head(source: Engine, target: Engine) -> None:
    def head(engine: Engine):
        with engine.connect() as c:
            if not engine.dialect.has_table(c, "alembic_version"):
                return None
            return c.execute(text("SELECT version_num FROM alembic_version")).scalar()

    s, t = head(source), head(target)
    if s is None or t is None:
        sys.exit(f"Refusing: alembic_version missing (source={s!r}, target={t!r}). "
                 "Run migrations on both first.")
    if s != t:
        sys.exit(f"Refusing: schema mismatch. source head={s}, target head={t}. "
                 "Bring both to the same Alembic head before copying.")
    print(f"Schema check OK — both at alembic head {s}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Copy all business tables source -> target.")
    ap.add_argument("--source", required=True, help="SQLAlchemy URL to read FROM (e.g. sqlite:////data/portal_dev.db)")
    ap.add_argument("--target", help="SQLAlchemy URL to write TO (default: app DATABASE_URL)")
    ap.add_argument("--wipe", action="store_true", help="delete existing rows in the target first")
    ap.add_argument("--commit", action="store_true", help="actually write (otherwise a dry run)")
    args = ap.parse_args()

    from app.core.config import settings
    target_url = args.target or settings.database_url

    source = create_engine(args.source)
    target = create_engine(target_url)
    print(f"SOURCE  {source.url}")
    print(f"TARGET  {target.url}")
    print(f"MODE    {'COMMIT (writing)' if args.commit else 'DRY RUN (no writes)'}"
          f"{' + WIPE' if args.wipe else ''}\n")

    _assert_same_head(source, target)

    tables = sorted_business_tables()

    # Read every table's rows up front (small dataset), so the write phase is a
    # single short transaction.
    data: dict[str, list[dict]] = {}
    with source.connect() as sc:
        for table in tables:
            rows = [dict(m) for m in sc.execute(select(table)).mappings()]
            data[table.name] = rows

    print(f"{'TABLE':<32}{'SOURCE':>8}{'TARGET(before)':>16}")
    with target.connect() as tc:
        for table in tables:
            before = tc.execute(select(func.count()).select_from(table)).scalar()
            print(f"{table.name:<32}{len(data[table.name]):>8}{before:>16}")
    total = sum(len(v) for v in data.values())
    print(f"\nTotal rows to copy: {total}")

    if not args.commit:
        print("\nDry run — nothing written. Re-run with --wipe --commit to apply.")
        return

    with target.begin() as tc:
        _fk_off(tc)
        if args.wipe:
            for table in reversed(tables):  # children first
                tc.execute(table.delete())
        for table in tables:
            rows = data[table.name]
            for i in range(0, len(rows), BATCH):
                tc.execute(table.insert(), rows[i:i + BATCH])
        _resync_sequences(tc, tables)
        _fk_on(tc)

    # Verify.
    print("\nVerification (target counts after copy):")
    ok = True
    with target.connect() as tc:
        for table in tables:
            after = tc.execute(select(func.count()).select_from(table)).scalar()
            want = len(data[table.name])
            flag = "" if after == want else "  <-- MISMATCH"
            if after != want:
                ok = False
            print(f"  {table.name:<32}{after:>8} / {want}{flag}")
    print("\nDONE — all tables match." if ok else "\nDONE WITH MISMATCHES — investigate above.")
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
