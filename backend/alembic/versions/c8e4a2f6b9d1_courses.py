"""courses

Courses tab: a course is a bundle of teaching material stored in the database
(course_files), the items on its slides / book / tasks / task answers / tools
shelves — files of the course or external links (course_materials), and
each learner's ticks (course_progress).

Two new privileges: courses.view goes to the preset Lead and Member levels;
Board, defined as "everything but users.manage", gets both.

Revision ID: c8e4a2f6b9d1
Revises: b7d3f1a9c5e2
Create Date: 2026-10-16

"""
import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c8e4a2f6b9d1"
down_revision: Union[str, None] = "b7d3f1a9c5e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

GRANTS = {
    "Board": ["courses.view", "courses.manage"],
    "Lead": ["courses.view"],
    "Member": ["courses.view"],
}


def _grant(add: bool) -> None:
    bind = op.get_bind()
    levels = sa.table("access_levels", sa.column("id"), sa.column("name"), sa.column("privileges"))
    for lid, name, privs in bind.execute(sa.select(levels.c.id, levels.c.name, levels.c.privileges)):
        new = set(GRANTS.get(name, []))
        if not new:
            continue
        keys = set(json.loads(privs or "[]"))
        keys = keys | new if add else keys - new
        bind.execute(levels.update().where(levels.c.id == lid).values(privileges=json.dumps(sorted(keys))))


def upgrade() -> None:
    op.create_table(
        "courses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("cover_label", sa.String(length=40), nullable=True),
        sa.Column("accent", sa.String(length=20), nullable=False),
        sa.Column("cover_path", sa.String(length=500), nullable=True),
        sa.Column("is_published", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "course_files",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("course_id", sa.Integer(), nullable=False),
        sa.Column("path", sa.String(length=500), nullable=False),
        sa.Column("media_type", sa.String(length=100), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("course_id", "path"),
    )
    op.create_index("ix_course_files_course_id", "course_files", ["course_id"])
    op.create_table(
        "course_materials",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("course_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("path", sa.String(length=500), nullable=True),
        sa.Column("external_url", sa.String(length=1000), nullable=True),
        sa.Column("unit", sa.Integer(), nullable=True),
        sa.Column("unit_label", sa.String(length=100), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("is_released", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("course_id", "path"),
    )
    op.create_index("ix_course_materials_course_id", "course_materials", ["course_id"])
    op.create_table(
        "course_progress",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("material_id", sa.Integer(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["material_id"], ["course_materials.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "material_id"),
    )
    op.create_index("ix_course_progress_material_id", "course_progress", ["material_id"])
    _grant(True)


def downgrade() -> None:
    _grant(False)
    op.drop_index("ix_course_progress_material_id", table_name="course_progress")
    op.drop_table("course_progress")
    op.drop_index("ix_course_materials_course_id", table_name="course_materials")
    op.drop_table("course_materials")
    op.drop_index("ix_course_files_course_id", table_name="course_files")
    op.drop_table("course_files")
    op.drop_table("courses")
