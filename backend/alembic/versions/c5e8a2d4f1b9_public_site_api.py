"""public_site_api: what the website can read and who it can recruit for

Adds the three things the marketing site needs to read the portal instead of
keeping its own copies:

  * positions.on_website — whether a real seat (and whoever holds it) is shown
    on the site's People page. Seats titled as a roster ("Software member")
    start hidden, so members are never listed by default; every other seat
    starts shown.
  * events.applications_open / events.public_summary — an event can recruit
    from the site's join form, with a short public pitch.
  * applications.event_id — which event an applicant asked to join (NULL = a
    general application).

Revision ID: c5e8a2d4f1b9
Revises: a3d7f1c9e5b2
Create Date: 2026-10-31

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c5e8a2d4f1b9"
down_revision: Union[str, None] = "a3d7f1c9e5b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("positions", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("on_website", sa.Boolean(), nullable=False, server_default=sa.true())
        )
    op.execute("UPDATE positions SET on_website = false WHERE lower(title) LIKE '%member%'")

    with op.batch_alter_table("events", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("applications_open", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch_op.add_column(sa.Column("public_summary", sa.Text(), nullable=True))

    with op.batch_alter_table("applications", schema=None) as batch_op:
        batch_op.add_column(sa.Column("event_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_applications_event_id", "events", ["event_id"], ["id"], ondelete="SET NULL"
        )
        batch_op.create_index("ix_applications_event_id", ["event_id"])


def downgrade() -> None:
    with op.batch_alter_table("applications", schema=None) as batch_op:
        batch_op.drop_index("ix_applications_event_id")
        batch_op.drop_constraint("fk_applications_event_id", type_="foreignkey")
        batch_op.drop_column("event_id")
    with op.batch_alter_table("events", schema=None) as batch_op:
        batch_op.drop_column("public_summary")
        batch_op.drop_column("applications_open")
    with op.batch_alter_table("positions", schema=None) as batch_op:
        batch_op.drop_column("on_website")
