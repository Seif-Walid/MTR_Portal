"""rename competitions to events (tables, columns, data tokens)

The "Competitions" tab became the generic "Events" entity long ago, but the
schema and a handful of stored string tokens kept the old name. This renames
them everywhere so nothing internal still says "competition" except the one
place it legitimately should — the seeded *Competition* event kind (its
`event_kinds.slug`/`name` are data, not touched here).

Renames:
  - tables: competitions -> events, competition_categories -> event_categories,
    competition_teams -> event_teams, competition_team_members -> event_team_members
  - columns: event_categories.competition_id -> event_id,
    inventory_allocations.competition_id -> event_id
  - data tokens: positions.entity_type 'competition' -> 'event';
    role_templates.event 'competition_created' -> 'event_created';
    inventory_allocations.purpose 'competition' -> 'event';
    audit_log.domain 'competitions' -> 'events' and entity_type
    'competition'/'competition_team' -> 'event'/'event_team';
    access_levels.privileges JSON keys 'competitions.*' -> 'events.*'

Portable across SQLite (>= 3.25, native RENAME TABLE/COLUMN with FK follow)
and PostgreSQL. FK constraint and index *names* are intentionally left as-is
(cosmetic stale names); they keep functioning against the renamed objects.

Revision ID: b2f4e6a8c1d0
Revises: a1d4e7b90c33
Create Date: 2026-08-09
"""
from alembic import op
import sqlalchemy as sa


revision = "b2f4e6a8c1d0"
down_revision = "a1d4e7b90c33"
branch_labels = None
depends_on = None


def _rewrite_privileges(old_prefix: str, new_prefix: str) -> None:
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, privileges FROM access_levels")).fetchall()
    for rid, priv in rows:
        if priv and old_prefix in priv:
            bind.execute(
                sa.text("UPDATE access_levels SET privileges = :p WHERE id = :i"),
                {"p": priv.replace(old_prefix, new_prefix), "i": rid},
            )


def upgrade() -> None:
    # 1. tables (child FK references follow automatically on both dialects)
    op.rename_table("competitions", "events")
    op.rename_table("competition_categories", "event_categories")
    op.rename_table("competition_teams", "event_teams")
    op.rename_table("competition_team_members", "event_team_members")

    # 2. FK columns
    op.execute("ALTER TABLE event_categories RENAME COLUMN competition_id TO event_id")
    op.execute("ALTER TABLE inventory_allocations RENAME COLUMN competition_id TO event_id")

    # 3. stored string tokens
    op.execute("UPDATE positions SET entity_type = 'event' WHERE entity_type = 'competition'")
    op.execute("UPDATE role_templates SET event = 'event_created' WHERE event = 'competition_created'")
    op.execute("UPDATE inventory_allocations SET purpose = 'event' WHERE purpose = 'competition'")
    op.execute("UPDATE audit_log SET domain = 'events' WHERE domain = 'competitions'")
    op.execute("UPDATE audit_log SET entity_type = 'event' WHERE entity_type = 'competition'")
    op.execute("UPDATE audit_log SET entity_type = 'event_team' WHERE entity_type = 'competition_team'")

    # 4. access-level privilege keys (JSON text, rewritten in Python for portability)
    _rewrite_privileges("competitions.", "events.")


def downgrade() -> None:
    _rewrite_privileges("events.", "competitions.")

    op.execute("UPDATE audit_log SET entity_type = 'competition_team' WHERE entity_type = 'event_team'")
    op.execute("UPDATE audit_log SET entity_type = 'competition' WHERE entity_type = 'event'")
    op.execute("UPDATE audit_log SET domain = 'competitions' WHERE domain = 'events'")
    op.execute("UPDATE inventory_allocations SET purpose = 'competition' WHERE purpose = 'event'")
    op.execute("UPDATE role_templates SET event = 'competition_created' WHERE event = 'event_created'")
    op.execute("UPDATE positions SET entity_type = 'competition' WHERE entity_type = 'event'")

    op.execute("ALTER TABLE inventory_allocations RENAME COLUMN event_id TO competition_id")
    op.execute("ALTER TABLE event_categories RENAME COLUMN event_id TO competition_id")

    op.rename_table("event_team_members", "competition_team_members")
    op.rename_table("event_teams", "competition_teams")
    op.rename_table("event_categories", "competition_categories")
    op.rename_table("events", "competitions")
