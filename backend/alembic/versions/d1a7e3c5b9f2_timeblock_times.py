"""timeblock_times: optional time-of-day on team time blocks

Revision ID: d1a7e3c5b9f2
Revises: c9f2d4a6e8b1
Create Date: 2026-10-24

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "d1a7e3c5b9f2"
down_revision: Union[str, None] = "c9f2d4a6e8b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("time_blocks") as batch:
        batch.add_column(sa.Column("start_time", sa.Time(), nullable=True))
        batch.add_column(sa.Column("end_time", sa.Time(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("time_blocks") as batch:
        batch.drop_column("end_time")
        batch.drop_column("start_time")
