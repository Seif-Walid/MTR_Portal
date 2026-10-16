"""course material preview_path

Adds course_materials.preview_path: the stored path of an office file's cached
PDF rendition, so the viewer shows slides and docs inline instead of only
offering a download. NULL for files that need no rendition.

Revision ID: d4a7c2e9f1b3
Revises: c8e4a2f6b9d1
Create Date: 2026-10-17

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d4a7c2e9f1b3"
down_revision: Union[str, None] = "c8e4a2f6b9d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("course_materials", sa.Column("preview_path", sa.String(length=600), nullable=True))


def downgrade() -> None:
    op.drop_column("course_materials", "preview_path")
