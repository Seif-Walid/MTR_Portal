"""tasks: remember where a card sits in its board column

Revision ID: a7c9e1b3d5f2
Revises: f3b5d7e9a1c2
Create Date: 2026-11-25

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a7c9e1b3d5f2"
down_revision: Union[str, None] = "f3b5d7e9a1c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("tasks") as batch:
        batch.add_column(sa.Column("board_rank", sa.Float(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("tasks") as batch:
        batch.drop_column("board_rank")
