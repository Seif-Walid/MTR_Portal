"""entry requests and an MTR ID for everyone

Signing up on the portal no longer makes an account: it files an application
(source "portal") that a reviewer accepts or declines, carrying the password
the person chose so an accepted request can sign straight in. Everyone who
had no MTR ID (bootstrap admins, self-made accounts) is numbered after the
current highest.

Revision ID: c4d8e2f6a9b1
Revises: b9d1f3a5c7e2
Create Date: 2026-11-23

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c4d8e2f6a9b1"
down_revision: Union[str, None] = "b9d1f3a5c7e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _number(mtr_id: str | None) -> int:
    digits = "".join(ch for ch in (mtr_id or "") if ch.isdigit())
    return int(digits) if digits else 0


def upgrade() -> None:
    with op.batch_alter_table("applications") as batch:
        batch.add_column(sa.Column("source", sa.String(20), nullable=False, server_default="website"))
        batch.add_column(sa.Column("password_hash", sa.String(255), nullable=True))

    bind = op.get_bind()
    taken = [r[0] for r in bind.execute(sa.text("SELECT mtr_id FROM users WHERE mtr_id IS NOT NULL"))]
    highest = max((_number(m) for m in taken), default=0)
    missing = [r[0] for r in bind.execute(sa.text("SELECT id FROM users WHERE mtr_id IS NULL ORDER BY id"))]
    for uid in missing:
        highest += 1
        bind.execute(sa.text("UPDATE users SET mtr_id = :m WHERE id = :id"),
                     {"m": f"MTR-{highest:03d}", "id": uid})


def downgrade() -> None:
    # the MTR IDs handed out stay: they may already be printed on badges and sheets
    with op.batch_alter_table("applications") as batch:
        batch.drop_column("password_hash")
        batch.drop_column("source")
