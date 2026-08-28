"""hall of fame awards on events and teams

Adds the two columns the public Hall of Fame reads:
  events.awards      — JSON list of competition-wide placements
  event_teams.award  — a single per-team placement string

Both nullable; existing rows keep NULL. Uses batch_alter_table so the migration
also runs on SQLite (dev), where ALTER lacks native ADD COLUMN for some ops.

Revision ID: e6b2d4f80a11
Revises: d4e7b1a92c53
Create Date: 2026-08-28 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e6b2d4f80a11'
down_revision: Union[str, None] = 'd4e7b1a92c53'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('events', schema=None) as batch_op:
        batch_op.add_column(sa.Column('awards', sa.JSON(), nullable=True))
    with op.batch_alter_table('event_teams', schema=None) as batch_op:
        batch_op.add_column(sa.Column('award', sa.String(length=255), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('event_teams', schema=None) as batch_op:
        batch_op.drop_column('award')
    with op.batch_alter_table('events', schema=None) as batch_op:
        batch_op.drop_column('awards')
