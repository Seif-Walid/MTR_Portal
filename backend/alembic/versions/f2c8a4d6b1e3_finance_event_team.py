"""finance_event_team: tie spendings and dues enrolments to an event team

Adds a nullable event_team_id foreign key to spendings and dues_enrollments.

Revision ID: f2c8a4d6b1e3
Revises: e4b7c9a1d3f5
Create Date: 2026-11-05

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f2c8a4d6b1e3"
down_revision: Union[str, None] = "e4b7c9a1d3f5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = ("spendings", "dues_enrollments")


def upgrade() -> None:
    for table in TABLES:
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("event_team_id", sa.Integer(), nullable=True))
            batch.create_index(f"ix_{table}_event_team_id", ["event_team_id"])
            batch.create_foreign_key(
                f"fk_{table}_event_team_id", "event_teams",
                ["event_team_id"], ["id"], ondelete="SET NULL",
            )


def downgrade() -> None:
    for table in TABLES:
        with op.batch_alter_table(table) as batch:
            batch.drop_constraint(f"fk_{table}_event_team_id", type_="foreignkey")
            batch.drop_index(f"ix_{table}_event_team_id")
            batch.drop_column("event_team_id")
