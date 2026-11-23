"""finance: cash holders are portal accounts, dues roster from event teams

Money is now logged by the account that physically took or paid it, never
picked from a list: `holder_id` (→ users) on dues payments, spendings and
received funding, `from_user_id`/`to_user_id` on cash hand-overs. Backfilled
from the old finance party's linked account; rows whose party has no account
keep the party column as a read-only "legacy holder" (printed below so they can
be linked once).

Funding lines can now be *received* (date, method, holder) so sponsor money
reaches the cash balances, and point at a sponsor contact (`party_id`).
Spendings can name the supplier they paid (`payee_party_id`).

Who owes dues is derived from event teams: an event carries the dues tier its
members owe (`events.dues_tier_id`); a dues enrolment becomes an exception
(tier override, waiver, manual addition), so its tier is optional.

Levels that could edit the books get the new `finance.handle_cash` privilege,
so nobody who logs money today loses it on deploy.

Revision ID: d6f1a3c5e7b9
Revises: c4d8e2f6a9b1
Create Date: 2026-11-23

"""
import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d6f1a3c5e7b9"
down_revision: Union[str, None] = "c4d8e2f6a9b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PRIVILEGE = "finance.handle_cash"

# (table, column, target table, ondelete)
FKS = [
    ("dues_payments", "holder_id", "users", "SET NULL"),
    ("spendings", "holder_id", "users", "SET NULL"),
    ("spendings", "payee_party_id", "finance_parties", "SET NULL"),
    ("funding_lines", "holder_id", "users", "SET NULL"),
    ("funding_lines", "party_id", "finance_parties", "SET NULL"),
    ("funding_lines", "method_id", "finance_options", "SET NULL"),
    ("cash_transfers", "from_user_id", "users", "SET NULL"),
    ("cash_transfers", "to_user_id", "users", "SET NULL"),
    ("events", "dues_tier_id", "dues_tiers", "SET NULL"),
]

# old party column → new account column, per table
BACKFILL = [
    ("dues_payments", "received_by_id", "holder_id"),
    ("spendings", "paid_by_id", "holder_id"),
    ("cash_transfers", "from_party_id", "from_user_id"),
    ("cash_transfers", "to_party_id", "to_user_id"),
]


def _privilege(add: bool) -> None:
    bind = op.get_bind()
    levels = sa.table("access_levels", sa.column("id"), sa.column("privileges"))
    for lid, privs in bind.execute(sa.select(levels.c.id, levels.c.privileges)):
        keys = set(json.loads(privs or "[]"))
        if add and "finance.edit" in keys:
            keys.add(PRIVILEGE)
        elif not add:
            keys.discard(PRIVILEGE)
        else:
            continue
        bind.execute(levels.update().where(levels.c.id == lid).values(privileges=json.dumps(sorted(keys))))


def upgrade() -> None:
    by_table: dict[str, list[tuple[str, str, str]]] = {}
    for table, col, target, ondelete in FKS:
        by_table.setdefault(table, []).append((col, target, ondelete))
    for table, cols in by_table.items():
        with op.batch_alter_table(table) as batch:
            for col, _target, _od in cols:
                batch.add_column(sa.Column(col, sa.Integer(), nullable=True))
            if table == "funding_lines":
                batch.add_column(sa.Column("received_on", sa.Date(), nullable=True))
            for col, target, ondelete in cols:
                batch.create_index(f"ix_{table}_{col}", [col])
                batch.create_foreign_key(f"fk_{table}_{col}", target, [col], ["id"], ondelete=ondelete)

    with op.batch_alter_table("dues_enrollments") as batch:
        batch.alter_column("tier_id", existing_type=sa.Integer(), nullable=True)

    bind = op.get_bind()
    party_user = {
        pid: uid for pid, uid in bind.execute(sa.text("SELECT id, user_id FROM finance_parties"))
    }
    party_name = {pid: n for pid, n in bind.execute(sa.text("SELECT id, name FROM finance_parties"))}
    unlinked: dict[int, int] = {}
    for table, old, new in BACKFILL:
        for rid, pid in bind.execute(sa.text(f"SELECT id, {old} FROM {table} WHERE {old} IS NOT NULL")):
            uid = party_user.get(pid)
            if uid is None:
                unlinked[pid] = unlinked.get(pid, 0) + 1
                continue
            bind.execute(sa.text(f"UPDATE {table} SET {new} = :u WHERE id = :id"), {"u": uid, "id": rid})

    # sponsor contact by exact name
    by_name = {(n or "").strip().lower(): pid for pid, n in party_name.items()}
    for fid, source in bind.execute(sa.text("SELECT id, source FROM funding_lines")):
        pid = by_name.get((source or "").strip().lower())
        if pid is not None:
            bind.execute(sa.text("UPDATE funding_lines SET party_id = :p WHERE id = :id"), {"p": pid, "id": fid})

    for pid, n in sorted(unlinked.items()):
        print(f"  finance: party #{pid} “{party_name.get(pid)}” has no portal account — "
              f"{n} row(s) keep it as legacy holder; link it under Finance › Advanced › Contacts")

    _privilege(add=True)


def downgrade() -> None:
    _privilege(add=False)
    with op.batch_alter_table("dues_enrollments") as batch:
        batch.alter_column("tier_id", existing_type=sa.Integer(), nullable=False)
    by_table: dict[str, list[str]] = {}
    for table, col, _t, _o in FKS:
        by_table.setdefault(table, []).append(col)
    for table, cols in by_table.items():
        with op.batch_alter_table(table) as batch:
            for col in cols:
                batch.drop_constraint(f"fk_{table}_{col}", type_="foreignkey")
                batch.drop_index(f"ix_{table}_{col}")
                batch.drop_column(col)
            if table == "funding_lines":
                batch.drop_column("received_on")
