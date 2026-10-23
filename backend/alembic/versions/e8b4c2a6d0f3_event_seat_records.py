"""event_seat_records: keep who held an event's role seats once it is archived

Revision ID: e8b4c2a6d0f3
Revises: d1a7e3c5b9f2
Create Date: 2026-10-24

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "e8b4c2a6d0f3"
down_revision: Union[str, None] = "d1a7e3c5b9f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "event_seat_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("team_id", sa.Integer(), sa.ForeignKey("event_teams.id", ondelete="SET NULL"), nullable=True),
        sa.Column(
            "role_template_id", sa.Integer(),
            sa.ForeignKey("role_templates.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("entity_type", sa.String(20), nullable=True),
        sa.Column("entity_id", sa.Integer(), nullable=True),
        sa.Column("role", sa.String(255), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("user_name", sa.String(255), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_event_seat_records_event_id", "event_seat_records", ["event_id"])
    op.create_index("ix_event_seat_records_team_id", "event_seat_records", ["team_id"])
    op.create_index("ix_event_seat_records_user_id", "event_seat_records", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_event_seat_records_user_id", table_name="event_seat_records")
    op.drop_index("ix_event_seat_records_team_id", table_name="event_seat_records")
    op.drop_index("ix_event_seat_records_event_id", table_name="event_seat_records")
    op.drop_table("event_seat_records")
