"""applications: join applications from the website

The website's "Join the team" form now posts here instead of handing the
applicant off to email / Instagram. No privilege changes: reviewing reuses
members.view / members.edit.

Revision ID: b7d2f4a8c1e3
Revises: a6c9e2f4b8d1
Create Date: 2026-10-22

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b7d2f4a8c1e3"
down_revision: Union[str, None] = "a6c9e2f4b8d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "applications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("phone", sa.String(length=50), nullable=False),
        sa.Column("school", sa.String(length=255), nullable=False),
        sa.Column("year", sa.String(length=100), nullable=False),
        sa.Column("subteam", sa.String(length=50), nullable=True),
        sa.Column("motivation", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("member_id", sa.Integer(), nullable=True),
        sa.Column("client_hash", sa.String(length=64), nullable=True),
        sa.Column("reviewed_by_id", sa.Integer(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["member_id"], ["member_profiles.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["reviewed_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("applications", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_applications_email"), ["email"], unique=False)
        batch_op.create_index(batch_op.f("ix_applications_status"), ["status"], unique=False)
        batch_op.create_index(batch_op.f("ix_applications_client_hash"), ["client_hash"], unique=False)
        batch_op.create_index(batch_op.f("ix_applications_created_at"), ["created_at"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("applications", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_applications_created_at"))
        batch_op.drop_index(batch_op.f("ix_applications_client_hash"))
        batch_op.drop_index(batch_op.f("ix_applications_status"))
        batch_op.drop_index(batch_op.f("ix_applications_email"))
    op.drop_table("applications")
