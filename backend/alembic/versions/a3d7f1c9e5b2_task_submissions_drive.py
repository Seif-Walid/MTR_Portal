"""task_submissions_drive: attachments can be links or Google Drive files

Adds the portal's single Drive connection, and lets a task attachment be a
small local file (as before), a file in that Drive, or a link.

Revision ID: a3d7f1c9e5b2
Revises: f2c6a8e4b1d7
Create Date: 2026-10-25

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "a3d7f1c9e5b2"
down_revision: Union[str, None] = "f2c6a8e4b1d7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "drive_connections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("refresh_token", sa.Text(), nullable=False),
        sa.Column("root_folder_id", sa.String(128), nullable=True),
        sa.Column("connected_by_id", sa.Integer(),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=False),
    )
    with op.batch_alter_table("task_attachments", schema=None) as batch_op:
        batch_op.add_column(sa.Column("kind", sa.String(10), nullable=False, server_default="file"))
        batch_op.add_column(sa.Column("drive_file_id", sa.String(128), nullable=True))
        batch_op.add_column(sa.Column("url", sa.String(1000), nullable=True))
        batch_op.alter_column("stored_name", existing_type=sa.String(255), nullable=True)
    with op.batch_alter_table("task_attachments", schema=None) as batch_op:
        batch_op.alter_column("kind", server_default=None)


def downgrade() -> None:
    op.execute("DELETE FROM task_attachments WHERE stored_name IS NULL")
    with op.batch_alter_table("task_attachments", schema=None) as batch_op:
        batch_op.alter_column("stored_name", existing_type=sa.String(255), nullable=False)
        batch_op.drop_column("url")
        batch_op.drop_column("drive_file_id")
        batch_op.drop_column("kind")
    op.drop_table("drive_connections")
