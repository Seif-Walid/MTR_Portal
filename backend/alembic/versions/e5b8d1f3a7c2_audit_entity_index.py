"""audit_log (entity_type, entity_id) index

Every grid edit now writes one audit row per touched record, and the grid reads
them back per record (row history) and per table (recycle bin) — this index
keeps both lookups cheap as the log grows.

Revision ID: e5b8d1f3a7c2
Revises: d4a7c2e9f1b3
Create Date: 2026-10-17

"""
from typing import Sequence, Union

from alembic import op

revision: str = "e5b8d1f3a7c2"
down_revision: Union[str, None] = "d4a7c2e9f1b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("ix_audit_log_entity", "audit_log", ["entity_type", "entity_id"])


def downgrade() -> None:
    op.drop_index("ix_audit_log_entity", table_name="audit_log")
