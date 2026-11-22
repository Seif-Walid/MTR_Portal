"""Copy live Postgres (DATABASE_URL, read-only) into a fresh SQLite file at the same head.
Run inside the prod backend container from /app. Usage: python pull_live.py /tmp/live.db"""
import importlib, pkgutil, subprocess, sys, os
from sqlalchemy import create_engine, select, text, func

import app.domains as domains
for m in pkgutil.iter_modules(domains.__path__):
    try:
        importlib.import_module(f"app.domains.{m.name}.models")
    except ModuleNotFoundError:
        pass
from app.core.database import Base

out = sys.argv[1]
if os.path.exists(out):
    os.remove(out)
src_url = os.environ["DATABASE_URL"]
dst_url = f"sqlite:///{out}"
subprocess.run(["alembic", "upgrade", "head"], check=True, env={**os.environ, "DATABASE_URL": dst_url})

src, dst = create_engine(src_url), create_engine(dst_url)
with src.connect() as s, dst.connect() as d:
    sh = s.execute(text("select version_num from alembic_version")).scalar()
    dh = d.execute(text("select version_num from alembic_version")).scalar()
    assert sh == dh, (sh, dh)
    print("head", sh)

tables = [t for t in Base.metadata.sorted_tables if t.name != "alembic_version"]
with src.connect() as s:
    pg_tables = set(s.execute(text("select tablename from pg_tables where schemaname='public'")).scalars())
missing = pg_tables - {t.name for t in tables} - {"alembic_version"}
if missing:
    sys.exit(f"tables in Postgres not covered by models: {missing}")

with src.connect() as s, dst.begin() as d:
    d.execute(text("PRAGMA foreign_keys=OFF"))
    for t in reversed(tables):
        d.execute(t.delete())  # drop seed rows alembic may have inserted
    for t in tables:
        rows = [dict(r) for r in s.execute(select(t)).mappings()]
        for i in range(0, len(rows), 500):
            d.execute(t.insert(), rows[i:i + 500])
with src.connect() as s, dst.connect() as d:
    bad = 0
    for t in tables:
        a = s.execute(select(func.count()).select_from(t)).scalar()
        b = d.execute(select(func.count()).select_from(t)).scalar()
        if a != b:
            bad += 1
        if a or a != b:
            print(f"{t.name:<34}{a:>7}{b:>7}{'  MISMATCH' if a != b else ''}")
sys.exit(1 if bad else 0)
