"""course_tasks: link tasks to the course task sheet they hand out; drop ticks

Course progress is now how many of a course's task sheets the learner has
submitted through the Tasks tab, so the old self-ticked course_progress rows
are dropped.

Revision ID: f2c6a8e4b1d7
Revises: e8b4c2a6d0f3
Create Date: 2026-10-24

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "f2c6a8e4b1d7"
down_revision: Union[str, None] = "e8b4c2a6d0f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("tasks", schema=None) as batch_op:
        batch_op.add_column(sa.Column("course_material_id", sa.Integer(), nullable=True))
        batch_op.create_index(
            batch_op.f("ix_tasks_course_material_id"), ["course_material_id"], unique=False
        )
        batch_op.create_foreign_key(
            "fk_tasks_course_material_id_course_materials",
            "course_materials", ["course_material_id"], ["id"], ondelete="SET NULL",
        )
    op.drop_table("course_progress")


def downgrade() -> None:
    op.create_table(
        "course_progress",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column(
            "material_id", sa.Integer(),
            sa.ForeignKey("course_materials.id", ondelete="CASCADE"), primary_key=True,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_course_progress_material_id", "course_progress", ["material_id"])
    with op.batch_alter_table("tasks", schema=None) as batch_op:
        batch_op.drop_constraint("fk_tasks_course_material_id_course_materials", type_="foreignkey")
        batch_op.drop_index(batch_op.f("ix_tasks_course_material_id"))
        batch_op.drop_column("course_material_id")
