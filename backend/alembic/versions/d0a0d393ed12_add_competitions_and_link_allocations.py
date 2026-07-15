"""add competitions and link allocations

Revision ID: d0a0d393ed12
Revises: 3aa1c45b3a9c
Create Date: 2026-07-14 19:19:24.655514

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd0a0d393ed12'
down_revision: Union[str, None] = '3aa1c45b3a9c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Names for constraints reflected during SQLite batch recreate (the existing
# inventory_allocations FKs were created unnamed) plus the new competition FK.
NAMING_CONVENTION = {
    "fk": "fk_%(table_name)s_%(column_0_name)s",
    "ix": "ix_%(table_name)s_%(column_0_name)s",
}
FK_COMPETITION = "fk_inventory_allocations_competition_id"


def upgrade() -> None:
    op.create_table('competitions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('season', sa.String(length=50), nullable=True),
    sa.Column('location', sa.String(length=255), nullable=True),
    sa.Column('start_date', sa.Date(), nullable=True),
    sa.Column('end_date', sa.Date(), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('notes', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('competitions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_competitions_name'), ['name'], unique=True)
        batch_op.create_index(batch_op.f('ix_competitions_status'), ['status'], unique=False)

    with op.batch_alter_table(
        'inventory_allocations', schema=None, naming_convention=NAMING_CONVENTION
    ) as batch_op:
        batch_op.add_column(sa.Column('competition_id', sa.Integer(), nullable=True))
        batch_op.create_index(
            batch_op.f('ix_inventory_allocations_competition_id'), ['competition_id'], unique=False
        )
        batch_op.create_foreign_key(
            FK_COMPETITION, 'competitions', ['competition_id'], ['id'], ondelete='SET NULL'
        )


def downgrade() -> None:
    with op.batch_alter_table(
        'inventory_allocations', schema=None, naming_convention=NAMING_CONVENTION
    ) as batch_op:
        batch_op.drop_constraint(FK_COMPETITION, type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_inventory_allocations_competition_id'))
        batch_op.drop_column('competition_id')

    with op.batch_alter_table('competitions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_competitions_status'))
        batch_op.drop_index(batch_op.f('ix_competitions_name'))

    op.drop_table('competitions')
