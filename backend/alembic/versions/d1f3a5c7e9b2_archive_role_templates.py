"""archive role templates instead of deleting (keep existing seats)

Deleting an automatic role used to cascade-delete every position it had ever
produced, wiping the current occupants (real people's seats) and past org
structure. An automatic role must only govern *future* events, so a delete now
archives the template instead: it stops seating/chaining but leaves its
already-produced positions untouched.

- role_templates.archived: archived templates drop out of every chain/list.
- role_templates.sort_order made nullable: an archived template's slot is
  freed (set NULL) so renumbering the live templates can't collide with it.

Revision ID: d1f3a5c7e9b2
Revises: c3d5f7a9b1e2
Create Date: 2026-08-13
"""
from alembic import op
import sqlalchemy as sa


revision = "d1f3a5c7e9b2"
down_revision = "c3d5f7a9b1e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("role_templates") as batch:
        batch.add_column(
            sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch.alter_column("sort_order", existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    with op.batch_alter_table("role_templates") as batch:
        batch.alter_column("sort_order", existing_type=sa.Integer(), nullable=False)
        batch.drop_column("archived")
