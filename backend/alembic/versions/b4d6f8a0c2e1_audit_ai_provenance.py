"""audit: record when the AI made a change, through what, and who approved

Revision ID: b4d6f8a0c2e1
Revises: a7c9e1b3d5f2
"""

import sqlalchemy as sa
from alembic import op

revision = "b4d6f8a0c2e1"
down_revision = "a7c9e1b3d5f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("audit_log") as b:
        b.add_column(sa.Column("via", sa.String(120), nullable=True))
        b.add_column(sa.Column("approved_by_id", sa.Integer(), nullable=True))
        b.add_column(sa.Column("ai_action_id", sa.Integer(), nullable=True))
        b.create_foreign_key("fk_audit_log_approved_by", "users", ["approved_by_id"], ["id"], ondelete="SET NULL")
        b.create_index("ix_audit_log_via", ["via"])
    with op.batch_alter_table("ai_pending_actions") as b:
        b.add_column(sa.Column("via", sa.String(120), nullable=False, server_default="assistant"))


def downgrade() -> None:
    with op.batch_alter_table("ai_pending_actions") as b:
        b.drop_column("via")
    with op.batch_alter_table("audit_log") as b:
        b.drop_index("ix_audit_log_via")
        b.drop_constraint("fk_audit_log_approved_by", type_="foreignkey")
        b.drop_column("ai_action_id")
        b.drop_column("approved_by_id")
        b.drop_column("via")
