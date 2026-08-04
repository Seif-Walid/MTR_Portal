"""member profiles

Revision ID: a1d4e7b90c33
Revises: f3c1b8e07a24
Create Date: 2026-08-02 12:00:00.000000

Adds member_profiles: the biographical/contact roster record behind an
account (imported from the org's member database). One row per user at most,
every column optional. Purely additive — no change to existing tables.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a1d4e7b90c33"
down_revision: Union[str, None] = "f3c1b8e07a24"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "member_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("mtr_id", sa.String(length=20), nullable=True),
        sa.Column("national_id", sa.String(length=50), nullable=True),
        sa.Column("birthday", sa.Date(), nullable=True),
        sa.Column("university", sa.String(length=255), nullable=True),
        sa.Column("college", sa.String(length=255), nullable=True),
        sa.Column("major", sa.String(length=255), nullable=True),
        sa.Column("graduating_year", sa.Integer(), nullable=True),
        sa.Column("phone", sa.String(length=50), nullable=True),
        sa.Column("father_phone", sa.String(length=50), nullable=True),
        sa.Column("mother_phone", sa.String(length=50), nullable=True),
        sa.Column("uni_id", sa.String(length=50), nullable=True),
        sa.Column("location", sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"],
            name="fk_member_profiles_user_id", ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_member_profiles_user_id", "member_profiles", ["user_id"], unique=True
    )
    op.create_index(
        "ix_member_profiles_mtr_id", "member_profiles", ["mtr_id"], unique=True
    )


def downgrade() -> None:
    op.drop_index("ix_member_profiles_mtr_id", table_name="member_profiles")
    op.drop_index("ix_member_profiles_user_id", table_name="member_profiles")
    op.drop_table("member_profiles")
