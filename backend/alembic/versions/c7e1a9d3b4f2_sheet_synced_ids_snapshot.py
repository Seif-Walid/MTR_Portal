"""add sheet_exports.synced_ids for the two-way live mirror

The live two-way DB<->Sheets sync diffs the sheet against the id set present at
the previous reconcile to tell an app-created row (keep + push) from a
sheet-deleted row (delete in the DB). That snapshot is stored per tab as a JSON
list in this new column. Defaults to '[]' so existing rows behave as "nothing
synced yet" (a safe first reconcile that deletes nothing).

Revision ID: c7e1a9d3b4f2
Revises: b2f4e6a8c1d0
Create Date: 2026-08-11
"""
from alembic import op
import sqlalchemy as sa


revision = "c7e1a9d3b4f2"
down_revision = "b2f4e6a8c1d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sheet_exports",
        sa.Column("synced_ids", sa.Text(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("sheet_exports", "synced_ids")
