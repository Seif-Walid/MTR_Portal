"""ai: personal agent tokens no longer expire, and record their last use

A token minted from "Connect your AI agent" now stays valid until its owner
revokes it, so `expires_at` becomes nullable (chat tokens still expire).
`last_used_at` lets the connect dialog show which agents are actually in use.

Revision ID: e8a2c4f6b0d1
Revises: d6f1a3c5e7b9
Create Date: 2026-11-24

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e8a2c4f6b0d1"
down_revision: Union[str, None] = "d6f1a3c5e7b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("ai_tokens") as batch:
        batch.alter_column("expires_at", existing_type=sa.DateTime(timezone=True), nullable=True)
        batch.add_column(sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.execute("DELETE FROM ai_tokens WHERE expires_at IS NULL")
    with op.batch_alter_table("ai_tokens") as batch:
        batch.drop_column("last_used_at")
        batch.alter_column("expires_at", existing_type=sa.DateTime(timezone=True), nullable=False)
