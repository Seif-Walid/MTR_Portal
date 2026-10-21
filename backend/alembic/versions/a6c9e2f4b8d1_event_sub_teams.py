"""event sub-teams: optional parent team

An event team may now sit inside another team of the same category. NULL keeps
today's flat behaviour, so every existing team stays a top-level team.

Revision ID: a6c9e2f4b8d1
Revises: e5b8d1f3a7c2
Create Date: 2026-10-22

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "a6c9e2f4b8d1"
down_revision: Union[str, None] = "e5b8d1f3a7c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("event_teams", schema=None) as batch_op:
        batch_op.add_column(sa.Column("parent_team_id", sa.Integer(), nullable=True))
        batch_op.create_index(
            batch_op.f("ix_event_teams_parent_team_id"), ["parent_team_id"], unique=False
        )
        batch_op.create_foreign_key(
            "fk_event_teams_parent_team_id_event_teams",
            "event_teams", ["parent_team_id"], ["id"], ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("event_teams", schema=None) as batch_op:
        batch_op.drop_constraint("fk_event_teams_parent_team_id_event_teams", type_="foreignkey")
        batch_op.drop_index(batch_op.f("ix_event_teams_parent_team_id"))
        batch_op.drop_column("parent_team_id")
