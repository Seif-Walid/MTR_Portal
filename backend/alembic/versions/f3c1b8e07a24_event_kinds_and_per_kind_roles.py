"""event kinds and per-kind roles

Revision ID: f3c1b8e07a24
Revises: e5a9c8b4d2f1
Create Date: 2026-07-21 12:00:00.000000

Adds admin-configurable event kinds, a kind_id on competitions (the generic
event entity), and a per-kind event_kind_id on role_templates. No event kinds
are shipped: a fresh install starts with Events empty (kinds are the admin's
data, created on the site). The one exception is data preservation — if the
database already has competitions, a single "Competition" kind is created and
those existing rows are assigned to it so nothing is orphaned. Purely
additive — no data-shape change, no data loss.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f3c1b8e07a24'
down_revision: Union[str, None] = 'e5a9c8b4d2f1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NAMING_CONVENTION = {"fk": "fk_%(table_name)s_%(column_0_name)s"}
FK_COMP_KIND = "fk_competitions_kind_id"
FK_TPL_KIND = "fk_role_templates_event_kind_id"


def upgrade() -> None:
    bind = op.get_bind()

    op.create_table(
        "event_kinds",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("slug", sa.String(length=50), nullable=False, unique=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("event_label", sa.String(length=100), nullable=False),
        sa.Column("category_label", sa.String(length=100), nullable=False),
        sa.Column("team_label", sa.String(length=100), nullable=False),
        sa.Column("member_label", sa.String(length=100), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, unique=True),
    )

    with op.batch_alter_table("competitions", schema=None, naming_convention=NAMING_CONVENTION) as batch_op:
        batch_op.add_column(sa.Column("kind_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(FK_COMP_KIND, "event_kinds", ["kind_id"], ["id"], ondelete="SET NULL")

    # Data preservation only: if this DB already has competitions, they need a
    # kind so they don't vanish from the Events tabs. Create a single
    # "Competition" kind and assign them. A fresh install (no competitions)
    # gets no kinds at all — Events stays empty until the admin defines one.
    has_competitions = bind.execute(sa.text("SELECT COUNT(*) FROM competitions")).scalar()
    if has_competitions:
        bind.execute(sa.text(
            "INSERT INTO event_kinds (slug, name, event_label, category_label, team_label,"
            " member_label, sort_order) VALUES"
            " ('competition', 'Competition', 'Competition', 'Category', 'Team', 'Member', 1)"
        ))
        competition_kind_id = bind.execute(
            sa.text("SELECT id FROM event_kinds WHERE slug = 'competition'")
        ).scalar_one()
        bind.execute(sa.text("UPDATE competitions SET kind_id = :k"), {"k": competition_kind_id})

    with op.batch_alter_table("role_templates", schema=None, naming_convention=NAMING_CONVENTION) as batch_op:
        batch_op.add_column(sa.Column("event_kind_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(FK_TPL_KIND, "event_kinds", ["event_kind_id"], ["id"], ondelete="CASCADE")
    # leave existing role templates kind-agnostic (NULL = every kind) — they
    # keep firing for competitions exactly as before, now also for any kind


def downgrade() -> None:
    with op.batch_alter_table("role_templates", schema=None, naming_convention=NAMING_CONVENTION) as batch_op:
        batch_op.drop_constraint(FK_TPL_KIND, type_="foreignkey")
        batch_op.drop_column("event_kind_id")
    with op.batch_alter_table("competitions", schema=None, naming_convention=NAMING_CONVENTION) as batch_op:
        batch_op.drop_constraint(FK_COMP_KIND, type_="foreignkey")
        batch_op.drop_column("kind_id")
    op.drop_table("event_kinds")
