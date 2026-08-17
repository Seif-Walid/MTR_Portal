"""team time blocks on calendar

Revision ID: d4e7b1a92c53
Revises: c7e2a9f4d1b3
Create Date: 2026-08-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd4e7b1a92c53'
down_revision: Union[str, None] = 'c7e2a9f4d1b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'time_blocks',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('team_type', sa.String(length=10), nullable=False),
        sa.Column('event_team_id', sa.Integer(), nullable=True),
        sa.Column('position_id', sa.Integer(), nullable=True),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('end_date', sa.Date(), nullable=False),
        sa.Column('weekday_mask', sa.Integer(), nullable=False),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['event_team_id'], ['event_teams.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['position_id'], ['positions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('time_blocks', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_time_blocks_event_team_id'), ['event_team_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_time_blocks_position_id'), ['position_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('time_blocks', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_time_blocks_position_id'))
        batch_op.drop_index(batch_op.f('ix_time_blocks_event_team_id'))
    op.drop_table('time_blocks')
