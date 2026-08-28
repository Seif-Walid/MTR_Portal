"""per-membership competition role for the Hall of Fame

event_team_members.role — the free-form role a member held in a specific
competition (Electrical, CEO, Pilot · CTO, GUI, …), shown verbatim in the public
Hall of Fame. Distinct from User.department; nullable (many roster members have
no role recorded).

Revision ID: f7c3e5a91b22
Revises: e6b2d4f80a11
Create Date: 2026-08-28 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f7c3e5a91b22'
down_revision: Union[str, None] = 'e6b2d4f80a11'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('event_team_members', schema=None) as batch_op:
        batch_op.add_column(sa.Column('role', sa.String(length=100), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('event_team_members', schema=None) as batch_op:
        batch_op.drop_column('role')
