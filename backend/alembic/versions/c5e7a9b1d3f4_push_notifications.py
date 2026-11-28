"""push notifications: device subscriptions + the server's signing key

Revision ID: c5e7a9b1d3f4
Revises: b4d6f8a0c2e1
"""

import sqlalchemy as sa
from alembic import op

revision = "c5e7a9b1d3f4"
down_revision = "b4d6f8a0c2e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "push_subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("endpoint", sa.Text(), nullable=False, unique=True),
        sa.Column("p256dh", sa.String(200), nullable=False),
        sa.Column("auth", sa.String(100), nullable=False),
        sa.Column("origin", sa.String(200), nullable=False),
        sa.Column("device", sa.String(120), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_push_subscriptions_user_id", "push_subscriptions", ["user_id"])
    op.create_table(
        "push_keys",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("private_pem", sa.Text(), nullable=False),
        sa.Column("public_key", sa.String(120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("push_keys")
    op.drop_index("ix_push_subscriptions_user_id", table_name="push_subscriptions")
    op.drop_table("push_subscriptions")
