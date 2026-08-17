"""merge parent phones into a single multi-value guardian_phone

Replaces the two roster columns `father_phone` and `mother_phone` with one
`guardian_phone` column that holds one or more numbers, stored comma-separated
so the flat-text consumers (bulk editor, Sheets mirror, roster import) keep
treating it as an ordinary text cell.

Revision ID: c7e2a9f4d1b3
Revises: f3a1c2d4e5b6
Create Date: 2026-08-16
"""

from alembic import op
import sqlalchemy as sa

revision = "c7e2a9f4d1b3"
down_revision = "f3a1c2d4e5b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "member_profiles",
        sa.Column("guardian_phone", sa.String(length=255), nullable=True),
    )
    # Fold existing parent numbers into the combined cell. Blank and the "-"
    # placeholder count as empty; a value present in both parents is not
    # duplicated. Each concat piece defaults to '' so NULLs never propagate.
    op.execute(
        """
        UPDATE member_profiles SET guardian_phone = NULLIF(trim(
            CASE WHEN father_phone IS NOT NULL AND trim(father_phone) NOT IN ('', '-')
                 THEN trim(father_phone) ELSE '' END
            || CASE WHEN father_phone IS NOT NULL AND trim(father_phone) NOT IN ('', '-')
                    AND mother_phone IS NOT NULL AND trim(mother_phone) NOT IN ('', '-')
                    AND trim(father_phone) <> trim(mother_phone)
                    THEN ', ' ELSE '' END
            || CASE WHEN mother_phone IS NOT NULL AND trim(mother_phone) NOT IN ('', '-')
                    AND (father_phone IS NULL OR trim(father_phone) IN ('', '-')
                         OR trim(father_phone) <> trim(mother_phone))
                    THEN trim(mother_phone) ELSE '' END
        ), '')
        """
    )
    with op.batch_alter_table("member_profiles") as batch:
        batch.drop_column("father_phone")
        batch.drop_column("mother_phone")


def downgrade() -> None:
    op.add_column(
        "member_profiles",
        sa.Column("father_phone", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "member_profiles",
        sa.Column("mother_phone", sa.String(length=50), nullable=True),
    )
    # Best-effort restore: the whole combined cell goes back into father_phone
    # (portable across SQLite/Postgres); mother_phone stays empty. Splitting the
    # comma list back into two named columns is intentionally not attempted.
    op.execute("UPDATE member_profiles SET father_phone = guardian_phone")
    with op.batch_alter_table("member_profiles") as batch:
        batch.drop_column("guardian_phone")
