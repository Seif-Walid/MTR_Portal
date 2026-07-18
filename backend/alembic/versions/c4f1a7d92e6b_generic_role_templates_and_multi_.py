"""generic role templates and multi-occupant positions

Revision ID: c4f1a7d92e6b
Revises: 689a99d163d0
Create Date: 2026-07-18 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c4f1a7d92e6b'
down_revision: Union[str, None] = '689a99d163d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NAMING_CONVENTION = {
    "fk": "fk_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ix": "ix_%(table_name)s_%(column_0_name)s",
}
UQ_ROLE_TEMPLATES_ORDER = "uq_role_templates_sort_order"
UQ_POSITIONS_ROLE = "uq_positions_role_template_id"
FK_POSITIONS_ROLE_TEMPLATE = "fk_positions_role_template_id"
UQ_POSITION_OCCUPANTS = "uq_position_occupants_position_id"

positions = sa.table('positions', sa.column('id', sa.Integer), sa.column('occupant_id', sa.Integer))
position_occupants = sa.table(
    'position_occupants',
    sa.column('position_id', sa.Integer), sa.column('user_id', sa.Integer),
    sa.column('created_at', sa.DateTime),
)


def upgrade() -> None:
    op.create_table(
        'role_templates',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('title_template', sa.String(length=255), nullable=False),
        sa.Column('event', sa.String(length=30), nullable=False),
        sa.Column('sort_order', sa.Integer(), nullable=False),
        sa.Column('grants_management', sa.Boolean(), nullable=False),
        sa.Column('auto_assign_creator', sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('sort_order', name=UQ_ROLE_TEMPLATES_ORDER),
    )
    op.create_index('ix_role_templates_event', 'role_templates', ['event'], unique=False)

    op.create_table(
        'position_occupants',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('position_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['position_id'], ['positions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('position_id', 'user_id', name=UQ_POSITION_OCCUPANTS),
    )
    op.create_index(
        'ix_position_occupants_position_id', 'position_occupants', ['position_id'], unique=False
    )
    op.create_index(
        'ix_position_occupants_user_id', 'position_occupants', ['user_id'], unique=False
    )

    # carry every existing real seat's occupant forward into the new
    # many-occupants table *before* the old single-occupant column is
    # dropped below — a straight drop_column would silently destroy
    # whoever was actually seated in the org chart.
    conn = op.get_bind()
    now = sa.func.now()
    rows = conn.execute(
        sa.select(positions.c.id, positions.c.occupant_id).where(positions.c.occupant_id.is_not(None))
    ).fetchall()
    for position_id, occupant_id in rows:
        conn.execute(
            position_occupants.insert().values(position_id=position_id, user_id=occupant_id, created_at=now)
        )

    # positions: drop the old single occupant_id (now safely carried
    # forward above), add the role-template link. Any leftover auto-
    # managed positions from the never-shipped earlier draft of this
    # feature keep their real occupants but lose their (also never-
    # shipped) auto_kind linkage, which is fine — nothing real was ever
    # built on that schema.
    with op.batch_alter_table(
        'positions', schema=None, naming_convention=NAMING_CONVENTION
    ) as batch_op:
        batch_op.drop_index(batch_op.f('ix_positions_occupant_id'))
        batch_op.drop_column('occupant_id')
        batch_op.add_column(sa.Column('role_template_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('entity_type', sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column('entity_id', sa.Integer(), nullable=True))
        batch_op.create_index(
            batch_op.f('ix_positions_role_template_id'), ['role_template_id'], unique=False
        )
        batch_op.create_foreign_key(
            FK_POSITIONS_ROLE_TEMPLATE, 'role_templates', ['role_template_id'], ['id'],
            ondelete='SET NULL',
        )
        batch_op.create_unique_constraint(
            UQ_POSITIONS_ROLE, ['role_template_id', 'entity_type', 'entity_id']
        )

    op.create_table(
        'role_chain_root',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('position_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['position_id'], ['positions.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )

    # competition_teams: lead_id/coach_id are superseded by role-template
    # positions — who leads/coaches a team is now purely a matter of
    # occupancy, not a dedicated column.
    with op.batch_alter_table(
        'competition_teams', schema=None, naming_convention=NAMING_CONVENTION
    ) as batch_op:
        batch_op.drop_index(batch_op.f('ix_competition_teams_lead_id'))
        batch_op.drop_column('lead_id')

    # competition_pms: superseded by role-template positions with
    # grants_management=true — "who can manage this competition" now comes
    # from occupying one of those, not a dedicated PM table.
    op.drop_index('ix_competition_pms_user_id', table_name='competition_pms')
    op.drop_index('ix_competition_pms_competition_id', table_name='competition_pms')
    op.drop_table('competition_pms')


def downgrade() -> None:
    op.create_table(
        'competition_pms',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('competition_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['competition_id'], ['competitions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('competition_id', 'user_id'),
    )
    op.create_index('ix_competition_pms_competition_id', 'competition_pms', ['competition_id'], unique=False)
    op.create_index('ix_competition_pms_user_id', 'competition_pms', ['user_id'], unique=False)

    with op.batch_alter_table(
        'competition_teams', schema=None, naming_convention=NAMING_CONVENTION
    ) as batch_op:
        batch_op.add_column(sa.Column('lead_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            'fk_competition_teams_lead_id', 'users', ['lead_id'], ['id'], ondelete='SET NULL'
        )
        batch_op.create_index(batch_op.f('ix_competition_teams_lead_id'), ['lead_id'], unique=False)

    op.drop_table('role_chain_root')

    with op.batch_alter_table(
        'positions', schema=None, naming_convention=NAMING_CONVENTION
    ) as batch_op:
        batch_op.drop_constraint(UQ_POSITIONS_ROLE, type_='unique')
        batch_op.drop_constraint(FK_POSITIONS_ROLE_TEMPLATE, type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_positions_role_template_id'))
        batch_op.drop_column('entity_id')
        batch_op.drop_column('entity_type')
        batch_op.drop_column('role_template_id')
        batch_op.add_column(sa.Column('occupant_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_positions_occupant_id'), ['occupant_id'], unique=False)

    # best-effort carry back: a position can have many occupants going
    # forward but only one coming back, so this picks the earliest-added
    # occupant per position — same "earliest wins" convention used
    # elsewhere (e.g. which PM mirrors the org-chart seat).
    conn = op.get_bind()
    conn.execute(sa.text(
        "UPDATE positions SET occupant_id = ("
        "  SELECT po.user_id FROM position_occupants po"
        "  WHERE po.position_id = positions.id ORDER BY po.id LIMIT 1"
        ") WHERE EXISTS ("
        "  SELECT 1 FROM position_occupants po WHERE po.position_id = positions.id"
        ")"
    ))

    op.drop_index('ix_position_occupants_user_id', table_name='position_occupants')
    op.drop_index('ix_position_occupants_position_id', table_name='position_occupants')
    op.drop_table('position_occupants')

    op.drop_index('ix_role_templates_event', table_name='role_templates')
    op.drop_table('role_templates')
