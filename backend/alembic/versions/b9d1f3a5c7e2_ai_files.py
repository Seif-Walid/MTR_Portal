"""ai_files: spreadsheets and PDFs the assistant generates

Revision ID: b9d1f3a5c7e2
Revises: a7c3e9f1b5d2
Create Date: 2026-11-17

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b9d1f3a5c7e2"
down_revision: Union[str, None] = "a7c3e9f1b5d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ai_files",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("conversation_id", sa.Integer(),
                  sa.ForeignKey("ai_conversations.id", ondelete="CASCADE"), nullable=True),
        sa.Column("filename", sa.String(200), nullable=False),
        sa.Column("media_type", sa.String(120), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_ai_files_user_id", "ai_files", ["user_id"])
    op.create_index("ix_ai_files_conversation_id", "ai_files", ["conversation_id"])


def downgrade() -> None:
    op.drop_index("ix_ai_files_conversation_id", table_name="ai_files")
    op.drop_index("ix_ai_files_user_id", table_name="ai_files")
    op.drop_table("ai_files")
