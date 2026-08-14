"""drop rebuild_batches (Rebuild-from-Sheets feature removed)

The destructive Rebuild-from-Sheets path and its Data Sync admin page were
removed; only the live two-way mirror (sheet_exports tracking) remains. This
drops the now-orphaned audit table. Irreversible in practice — the downgrade
recreates the schema but not the historical rows.

Revision ID: f3a1c2d4e5b6
Revises: c7e1a9d3b4f2
Create Date: 2026-08-15
"""
from alembic import op
import sqlalchemy as sa


revision = "f3a1c2d4e5b6"
down_revision = "c7e1a9d3b4f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("rebuild_batches")


def downgrade() -> None:
    op.create_table(
        "rebuild_batches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("status", sa.String(length=20), nullable=False, index=True),
        sa.Column("spreadsheet_id", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("tab_counts", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("errors", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("snapshot_path", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
