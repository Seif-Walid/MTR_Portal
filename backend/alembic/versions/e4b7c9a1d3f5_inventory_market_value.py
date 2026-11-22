"""inventory_market_value: per-unit market value with its cited source

Adds the value columns to inventory_items. A value comes from a confirmed
Makers Electronics or Future Electronics Egypt listing (pinned by shop id /
handle so it can be re-priced) or is a manual, uncited estimate.

Revision ID: e4b7c9a1d3f5
Revises: d8a3f6c2e9b4
Create Date: 2026-10-31

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e4b7c9a1d3f5"
down_revision: Union[str, None] = "d8a3f6c2e9b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("inventory_items") as batch:
        batch.add_column(sa.Column("unit_value", sa.Numeric(12, 2), nullable=True))
        batch.add_column(sa.Column("value_currency", sa.String(3), nullable=True))
        batch.add_column(sa.Column("value_source", sa.String(20), nullable=True))
        batch.add_column(sa.Column("value_ref", sa.String(255), nullable=True))
        batch.add_column(sa.Column("value_title", sa.String(500), nullable=True))
        batch.add_column(sa.Column("value_url", sa.String(500), nullable=True))
        batch.add_column(sa.Column("value_note", sa.Text(), nullable=False, server_default=""))
        batch.add_column(sa.Column("value_checked_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("value_error", sa.String(255), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("inventory_items") as batch:
        for col in ("value_error", "value_checked_at", "value_note", "value_url", "value_title",
                    "value_ref", "value_source", "value_currency", "unit_value"):
            batch.drop_column(col)
