"""official long-form event name for the public Hall of Fame

Adds events.full_name — the official title of a competition ("MATE ROV
Competition") as opposed to the short internal handle ("MATE ROV 2026").

The marketing website carried these titles in its own bundled roster file while
the portal had nowhere to store them, so the portal could not actually be the
source of truth for the Hall of Fame. This migration adds the column and
backfills the four titles that only existed on the website, matching on the
event name. Events whose short name is already the full title stay NULL.

Revision ID: a5c2e8b71d09
Revises: f7c3e5a91b22
Create Date: 2026-08-28 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a5c2e8b71d09'
down_revision: Union[str, None] = 'f7c3e5a91b22'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# event name -> official full title, recovered from the website's bundled roster.
KNOWN_FULL_NAMES = {
    "MATE ROV 2026": "MATE ROV Competition",
    "MATE ROV 2025": "MATE ROV Competition",
    "Robotex 2025": "Robotex International",
    "Robotex 2024": "Robotex International",
    "RCS 2024": "Robotics Challenge Summit (RCS)",
}


def upgrade() -> None:
    with op.batch_alter_table('events', schema=None) as batch_op:
        batch_op.add_column(sa.Column('full_name', sa.String(length=255), nullable=True))

    events = sa.table(
        'events', sa.column('name', sa.String), sa.column('full_name', sa.String)
    )
    conn = op.get_bind()
    for name, full_name in KNOWN_FULL_NAMES.items():
        conn.execute(
            events.update().where(events.c.name == name).values(full_name=full_name)
        )


def downgrade() -> None:
    with op.batch_alter_table('events', schema=None) as batch_op:
        batch_op.drop_column('full_name')
