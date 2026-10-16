"""member database and finance books

The member database (roster, events record, participations) and the team's
finance books move off Google Sheets into the portal:

* member_profiles becomes the roster entity — a member may exist without a
  portal account (user_id nullable, roster name/email of its own), plus the
  roster's extra fields;
* events gain the event-record columns of the member database's Events sheet;
* event_participations: one row per (member x event);
* the finance books: seasons, pick-lists, parties, budget, spendings, dues
  (tiers, discounts, enrolments, payments), funding, payables, cash transfers;
* the Google Sheets mirror's bookkeeping table (sheet_exports) is dropped —
  the Sheets integration is gone;
* the Board preset level picks up the new roster/finance/dashboard privileges
  (it is defined as "everything but users.manage"); the data dashboard is
  Board-and-above only.

Revision ID: b7d3f1a9c5e2
Revises: a5c2e8b71d09
Create Date: 2026-10-16

"""
import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b7d3f1a9c5e2"
down_revision: Union[str, None] = "a5c2e8b71d09"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NEW_PRIVILEGES = ["members.view", "members.edit", "finance.view", "finance.edit", "dashboard.view"]


def _board_privileges(add: bool) -> None:
    bind = op.get_bind()
    levels = sa.table("access_levels", sa.column("id"), sa.column("name"), sa.column("privileges"))
    for lid, privs in bind.execute(sa.select(levels.c.id, levels.c.privileges).where(levels.c.name == "Board")):
        keys = set(json.loads(privs or "[]"))
        keys = keys | set(NEW_PRIVILEGES) if add else keys - set(NEW_PRIVILEGES)
        bind.execute(levels.update().where(levels.c.id == lid).values(privileges=json.dumps(sorted(keys))))


def upgrade() -> None:
    op.create_table('finance_options',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('list_key', sa.String(length=30), nullable=False),
    sa.Column('value', sa.String(length=100), nullable=False),
    sa.Column('sort_order', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('list_key', 'value')
    )
    with op.batch_alter_table('finance_options', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_finance_options_list_key'), ['list_key'], unique=False)

    op.create_table('finance_seasons',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('start_date', sa.Date(), nullable=True),
    sa.Column('end_date', sa.Date(), nullable=True),
    sa.Column('usd_rate', sa.Numeric(precision=14, scale=2, asdecimal=False), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('sort_order', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )
    op.create_table('dues_discounts',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('season_id', sa.Integer(), nullable=False),
    sa.Column('min_years', sa.Integer(), nullable=False),
    sa.Column('discount', sa.Numeric(precision=5, scale=4, asdecimal=False), nullable=False),
    sa.Column('label', sa.String(length=100), nullable=True),
    sa.ForeignKeyConstraint(['season_id'], ['finance_seasons.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('season_id', 'min_years')
    )
    with op.batch_alter_table('dues_discounts', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_dues_discounts_season_id'), ['season_id'], unique=False)

    op.create_table('dues_tiers',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('season_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('monthly_fee', sa.Numeric(precision=14, scale=2, asdecimal=False), nullable=False),
    sa.Column('months', sa.Integer(), nullable=False),
    sa.Column('one_time_fee', sa.Numeric(precision=14, scale=2, asdecimal=False), nullable=False),
    sa.Column('sort_order', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['season_id'], ['finance_seasons.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('season_id', 'name')
    )
    with op.batch_alter_table('dues_tiers', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_dues_tiers_season_id'), ['season_id'], unique=False)

    op.create_table('funding_lines',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('season_id', sa.Integer(), nullable=False),
    sa.Column('source', sa.String(length=255), nullable=False),
    sa.Column('type_id', sa.Integer(), nullable=True),
    sa.Column('amount', sa.Numeric(precision=14, scale=2, asdecimal=False), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('note', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['season_id'], ['finance_seasons.id'], ),
    sa.ForeignKeyConstraint(['type_id'], ['finance_options.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('funding_lines', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_funding_lines_season_id'), ['season_id'], unique=False)

    op.create_table('budget_lines',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('season_id', sa.Integer(), nullable=False),
    sa.Column('event_id', sa.Integer(), nullable=True),
    sa.Column('subsystem_id', sa.Integer(), nullable=True),
    sa.Column('item', sa.String(length=255), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('unit_price', sa.Numeric(precision=14, scale=2, asdecimal=False), nullable=False),
    sa.Column('required_qty', sa.Numeric(precision=12, scale=3, asdecimal=False), nullable=False),
    sa.Column('spare_qty', sa.Numeric(precision=12, scale=3, asdecimal=False), nullable=False),
    sa.Column('in_stock_qty', sa.Numeric(precision=12, scale=3, asdecimal=False), nullable=False),
    sa.Column('category_id', sa.Integer(), nullable=True),
    sa.Column('link_note', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['category_id'], ['finance_options.id'], ),
    sa.ForeignKeyConstraint(['event_id'], ['events.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['season_id'], ['finance_seasons.id'], ),
    sa.ForeignKeyConstraint(['subsystem_id'], ['finance_options.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('budget_lines', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_budget_lines_event_id'), ['event_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_budget_lines_season_id'), ['season_id'], unique=False)

    op.create_table('finance_parties',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('type_id', sa.Integer(), nullable=True),
    sa.Column('phone', sa.String(length=50), nullable=True),
    sa.Column('payment_handle', sa.String(length=255), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['type_id'], ['finance_options.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )
    op.create_table('cash_transfers',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('transferred_on', sa.Date(), nullable=True),
    sa.Column('from_party_id', sa.Integer(), nullable=True),
    sa.Column('from_method_id', sa.Integer(), nullable=True),
    sa.Column('amount', sa.Numeric(precision=14, scale=2, asdecimal=False), nullable=False),
    sa.Column('fees', sa.Numeric(precision=14, scale=2, asdecimal=False), nullable=False),
    sa.Column('to_party_id', sa.Integer(), nullable=True),
    sa.Column('to_method_id', sa.Integer(), nullable=True),
    sa.Column('note', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['from_method_id'], ['finance_options.id'], ),
    sa.ForeignKeyConstraint(['from_party_id'], ['finance_parties.id'], ),
    sa.ForeignKeyConstraint(['to_method_id'], ['finance_options.id'], ),
    sa.ForeignKeyConstraint(['to_party_id'], ['finance_parties.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('dues_enrollments',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('season_id', sa.Integer(), nullable=False),
    sa.Column('member_id', sa.Integer(), nullable=False),
    sa.Column('tier_id', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('maturity_override', sa.Integer(), nullable=True),
    sa.Column('note', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['member_id'], ['member_profiles.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['season_id'], ['finance_seasons.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tier_id'], ['dues_tiers.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('season_id', 'member_id')
    )
    with op.batch_alter_table('dues_enrollments', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_dues_enrollments_member_id'), ['member_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_dues_enrollments_season_id'), ['season_id'], unique=False)

    op.create_table('dues_payments',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('season_id', sa.Integer(), nullable=False),
    sa.Column('member_id', sa.Integer(), nullable=False),
    sa.Column('paid_on', sa.Date(), nullable=False),
    sa.Column('amount', sa.Numeric(precision=14, scale=2, asdecimal=False), nullable=False),
    sa.Column('method_id', sa.Integer(), nullable=True),
    sa.Column('received_by_id', sa.Integer(), nullable=True),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['member_id'], ['member_profiles.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['method_id'], ['finance_options.id'], ),
    sa.ForeignKeyConstraint(['received_by_id'], ['finance_parties.id'], ),
    sa.ForeignKeyConstraint(['season_id'], ['finance_seasons.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('dues_payments', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_dues_payments_member_id'), ['member_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_dues_payments_season_id'), ['season_id'], unique=False)

    op.create_table('event_participations',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('event_id', sa.Integer(), nullable=False),
    sa.Column('member_id', sa.Integer(), nullable=False),
    sa.Column('role', sa.String(length=255), nullable=True),
    sa.Column('team', sa.String(length=255), nullable=True),
    sa.Column('mentor', sa.String(length=255), nullable=True),
    sa.Column('rating', sa.String(length=50), nullable=True),
    sa.Column('registered_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['event_id'], ['events.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['member_id'], ['member_profiles.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('event_id', 'member_id')
    )
    with op.batch_alter_table('event_participations', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_event_participations_event_id'), ['event_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_event_participations_member_id'), ['member_id'], unique=False)

    op.create_table('payables',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('owed_to_id', sa.Integer(), nullable=True),
    sa.Column('description', sa.String(length=255), nullable=False),
    sa.Column('season_id', sa.Integer(), nullable=True),
    sa.Column('amount', sa.Numeric(precision=14, scale=2, asdecimal=False), nullable=False),
    sa.Column('due_date', sa.Date(), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('note', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['owed_to_id'], ['finance_parties.id'], ),
    sa.ForeignKeyConstraint(['season_id'], ['finance_seasons.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('spendings',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('season_id', sa.Integer(), nullable=False),
    sa.Column('event_id', sa.Integer(), nullable=True),
    sa.Column('spent_on', sa.Date(), nullable=True),
    sa.Column('item', sa.String(length=255), nullable=False),
    sa.Column('category_id', sa.Integer(), nullable=True),
    sa.Column('subcategory_id', sa.Integer(), nullable=True),
    sa.Column('count', sa.Numeric(precision=12, scale=3, asdecimal=False), nullable=False),
    sa.Column('unit_cost', sa.Numeric(precision=14, scale=2, asdecimal=False), nullable=False),
    sa.Column('method_id', sa.Integer(), nullable=True),
    sa.Column('paid_by_id', sa.Integer(), nullable=True),
    sa.Column('receipt', sa.Text(), nullable=True),
    sa.Column('note', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['category_id'], ['finance_options.id'], ),
    sa.ForeignKeyConstraint(['event_id'], ['events.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['method_id'], ['finance_options.id'], ),
    sa.ForeignKeyConstraint(['paid_by_id'], ['finance_parties.id'], ),
    sa.ForeignKeyConstraint(['season_id'], ['finance_seasons.id'], ),
    sa.ForeignKeyConstraint(['subcategory_id'], ['finance_options.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('spendings', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_spendings_event_id'), ['event_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_spendings_season_id'), ['season_id'], unique=False)


    with op.batch_alter_table("events", schema=None) as batch_op:
        batch_op.add_column(sa.Column('code', sa.String(length=30), nullable=True))
        batch_op.add_column(sa.Column('level', sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column('organizer', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('location', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('tracks', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('result', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('registered_count', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('participants_count', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('teams_count', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('mentors', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('captains', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('contact', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('budget_total', sa.Numeric(precision=14, scale=2, asdecimal=False), nullable=True))
        batch_op.add_column(sa.Column('actual_spend', sa.Numeric(precision=14, scale=2, asdecimal=False), nullable=True))
        batch_op.add_column(sa.Column('currency', sa.String(length=10), nullable=True))
        batch_op.add_column(sa.Column('funding_source', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('registration_form', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('roster_source', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('notes', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('prep_date', sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column('competition_days', sa.String(length=100), nullable=True))
        batch_op.create_index("ix_events_code", ["code"], unique=True)

    with op.batch_alter_table("member_profiles", schema=None) as batch_op:
        batch_op.add_column(sa.Column('full_name', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('email', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('guardian_kinship', sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column('joined_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('data_confidence', sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column('source_records', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('review_note', sa.Text(), nullable=True))
        batch_op.alter_column("user_id", existing_type=sa.Integer(), nullable=True)
        batch_op.create_index("ix_member_profiles_email", ["email"], unique=False)
        batch_op.drop_constraint("fk_member_profiles_user_id", type_="foreignkey")
        batch_op.create_foreign_key(
            "fk_member_profiles_user_id", "users", ["user_id"], ["id"], ondelete="SET NULL"
        )

    with op.batch_alter_table("sheet_exports", schema=None) as batch_op:
        batch_op.drop_index("ix_sheet_exports_tab")
    op.drop_table("sheet_exports")

    _board_privileges(add=True)


def downgrade() -> None:
    _board_privileges(add=False)

    op.create_table(
        "sheet_exports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tab", sa.String(length=50), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("is_dirty", sa.Boolean(), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=False),
        sa.Column("synced_ids", sa.Text(), server_default=sa.text("'[]'"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table('sheet_exports', schema=None) as batch_op:
        batch_op.create_index("ix_sheet_exports_tab", ["tab"], unique=True)

    with op.batch_alter_table('spendings', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_spendings_season_id'))
        batch_op.drop_index(batch_op.f('ix_spendings_event_id'))

    op.drop_table('spendings')
    op.drop_table('payables')
    with op.batch_alter_table('event_participations', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_event_participations_member_id'))
        batch_op.drop_index(batch_op.f('ix_event_participations_event_id'))

    op.drop_table('event_participations')
    with op.batch_alter_table('dues_payments', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_dues_payments_season_id'))
        batch_op.drop_index(batch_op.f('ix_dues_payments_member_id'))

    op.drop_table('dues_payments')
    with op.batch_alter_table('dues_enrollments', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_dues_enrollments_season_id'))
        batch_op.drop_index(batch_op.f('ix_dues_enrollments_member_id'))

    op.drop_table('dues_enrollments')
    op.drop_table('cash_transfers')
    op.drop_table('finance_parties')
    with op.batch_alter_table('budget_lines', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_budget_lines_season_id'))
        batch_op.drop_index(batch_op.f('ix_budget_lines_event_id'))

    op.drop_table('budget_lines')
    with op.batch_alter_table('funding_lines', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_funding_lines_season_id'))

    op.drop_table('funding_lines')
    with op.batch_alter_table('dues_tiers', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_dues_tiers_season_id'))

    op.drop_table('dues_tiers')
    with op.batch_alter_table('dues_discounts', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_dues_discounts_season_id'))

    op.drop_table('dues_discounts')
    op.drop_table('finance_seasons')
    with op.batch_alter_table('finance_options', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_finance_options_list_key'))

    op.drop_table('finance_options')

    # roster-only members (no account) cannot survive the NOT NULL user_id
    op.execute("DELETE FROM member_profiles WHERE user_id IS NULL")
    with op.batch_alter_table("member_profiles", schema=None) as batch_op:
        batch_op.drop_constraint("fk_member_profiles_user_id", type_="foreignkey")
        batch_op.create_foreign_key(
            "fk_member_profiles_user_id", "users", ["user_id"], ["id"], ondelete="CASCADE"
        )
        batch_op.drop_index("ix_member_profiles_email")
        batch_op.alter_column("user_id", existing_type=sa.Integer(), nullable=False)
        batch_op.drop_column("full_name")
        batch_op.drop_column("email")
        batch_op.drop_column("guardian_kinship")
        batch_op.drop_column("joined_at")
        batch_op.drop_column("data_confidence")
        batch_op.drop_column("source_records")
        batch_op.drop_column("review_note")

    with op.batch_alter_table("events", schema=None) as batch_op:
        batch_op.drop_index("ix_events_code")
        batch_op.drop_column("code")
        batch_op.drop_column("level")
        batch_op.drop_column("organizer")
        batch_op.drop_column("location")
        batch_op.drop_column("tracks")
        batch_op.drop_column("result")
        batch_op.drop_column("registered_count")
        batch_op.drop_column("participants_count")
        batch_op.drop_column("teams_count")
        batch_op.drop_column("mentors")
        batch_op.drop_column("captains")
        batch_op.drop_column("contact")
        batch_op.drop_column("budget_total")
        batch_op.drop_column("actual_spend")
        batch_op.drop_column("currency")
        batch_op.drop_column("funding_source")
        batch_op.drop_column("registration_form")
        batch_op.drop_column("roster_source")
        batch_op.drop_column("notes")
        batch_op.drop_column("prep_date")
        batch_op.drop_column("competition_days")
