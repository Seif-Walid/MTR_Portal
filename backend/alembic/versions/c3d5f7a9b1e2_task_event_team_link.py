"""task event-team link and team visibility

Revision ID: c3d5f7a9b1e2
Revises: b2f4e6a8c1d0
Create Date: 2026-08-11 02:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c3d5f7a9b1e2'
down_revision: Union[str, None] = 'b2f4e6a8c1d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('tasks', schema=None) as batch_op:
        batch_op.add_column(sa.Column('event_team_id', sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column('team_visible', sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch_op.create_index(
            batch_op.f('ix_tasks_event_team_id'), ['event_team_id'], unique=False
        )
        batch_op.create_foreign_key(
            'fk_tasks_event_team_id_event_teams',
            'event_teams', ['event_team_id'], ['id'], ondelete='SET NULL',
        )

    # existing rows are backfilled by the server_default above; drop it so
    # future inserts rely on the ORM-side default (matches the rest of the
    # schema, where defaults live in the model, not the DB).
    with op.batch_alter_table('tasks', schema=None) as batch_op:
        batch_op.alter_column('team_visible', server_default=None)


def downgrade() -> None:
    with op.batch_alter_table('tasks', schema=None) as batch_op:
        batch_op.drop_constraint('fk_tasks_event_team_id_event_teams', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_tasks_event_team_id'))
        batch_op.drop_column('team_visible')
        batch_op.drop_column('event_team_id')
