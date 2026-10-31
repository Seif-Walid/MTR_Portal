"""members_are_accounts: fold the roster into users — one person, one id

Until now a member (member_profiles row) and an account (users row) were two
entities with two id spaces: the roster could hold members with no account,
and participations / dues / applications pointed at roster ids while
everything else pointed at user ids — so every person picker came in two
flavours. This makes them one:

  * every roster column moves onto `users`;
  * every roster-only member gets an account. It is *unclaimed* — no usable
    password (hashed_password = "!") and no Google link — until its owner
    signs in with Google, registers with that email, or follows a reset mail.
    Members without an email get an account with email NULL (users.email is
    now nullable);
  * event_participations / dues_enrollments / dues_payments / applications
    keep their `member_id` column but it now references users.id;
  * member_profiles is dropped.

Names: an account keeps its own name (it is what the Hall of Fame and the
website show); a roster name that differed is kept in review_note so nothing
is lost.

Revision ID: d8a3f6c2e9b4
Revises: c5e8a2d4f1b9
Create Date: 2026-10-31

"""
from datetime import datetime, timezone
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "d8a3f6c2e9b4"
down_revision: Union[str, None] = "c5e8a2d4f1b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


UNUSABLE_PASSWORD = "!"

ROSTER_COLUMNS = [
    sa.Column("mtr_id", sa.String(20), nullable=True),
    sa.Column("national_id", sa.String(50), nullable=True),
    sa.Column("birthday", sa.Date(), nullable=True),
    sa.Column("university", sa.String(255), nullable=True),
    sa.Column("college", sa.String(255), nullable=True),
    sa.Column("major", sa.String(255), nullable=True),
    sa.Column("graduating_year", sa.Integer(), nullable=True),
    sa.Column("phone", sa.String(50), nullable=True),
    sa.Column("guardian_phone", sa.String(255), nullable=True),
    sa.Column("guardian_kinship", sa.String(50), nullable=True),
    sa.Column("uni_id", sa.String(50), nullable=True),
    sa.Column("location", sa.String(255), nullable=True),
    sa.Column("joined_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("data_confidence", sa.String(20), nullable=True),
    sa.Column("source_records", sa.Integer(), nullable=True),
    sa.Column("review_note", sa.Text(), nullable=True),
]
FIELDS = [c.name for c in ROSTER_COLUMNS]

# (table, ondelete) of every column that pointed at a roster row
MEMBER_REFS = [
    ("event_participations", "CASCADE"),
    ("dues_enrollments", "CASCADE"),
    ("dues_payments", "CASCADE"),
    ("applications", "SET NULL"),
]


def _note(*parts: str | None) -> str | None:
    text = "\n".join(p for p in parts if p)
    return text or None


def _repoint(bind, mapping: dict[int, int], target: str) -> None:
    """Rewrite every member_id through `mapping`, then point its foreign key at
    `target`. Ids are moved via their negatives first, so (event, member) and
    (season, member) uniqueness never trips on a half-done rewrite."""
    sqlite = bind.dialect.name == "sqlite"
    if not sqlite:
        for table, _ in MEMBER_REFS:
            op.drop_constraint(f"{table}_member_id_fkey", table, type_="foreignkey")
    for table, _ in MEMBER_REFS:
        for old, new in mapping.items():
            bind.execute(sa.text(f"UPDATE {table} SET member_id = :neg WHERE member_id = :old"),
                         {"neg": -new, "old": old})
        bind.execute(sa.text(f"UPDATE {table} SET member_id = -member_id WHERE member_id < 0"))
    for table, ondelete in MEMBER_REFS:
        if sqlite:
            # the key may be unnamed (the original one): batch mode reflects it
            # under the naming convention below
            fk = next(f for f in sa.inspect(bind).get_foreign_keys(table) if f["constrained_columns"] == ["member_id"])
            existing = fk["name"] or f"fk_{table}_member_id_{fk['referred_table']}"
            with op.batch_alter_table(
                table,
                naming_convention={"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"},
            ) as batch:
                batch.drop_constraint(existing, type_="foreignkey")
                batch.create_foreign_key(
                    f"{table}_member_id_fkey", target, ["member_id"], ["id"], ondelete=ondelete
                )
        else:
            op.create_foreign_key(
                f"{table}_member_id_fkey", table, target, ["member_id"], ["id"], ondelete=ondelete
            )


def upgrade() -> None:
    bind = op.get_bind()
    with op.batch_alter_table("users") as batch:
        for col in ROSTER_COLUMNS:
            batch.add_column(col.copy())
        batch.alter_column("email", existing_type=sa.String(255), nullable=True)
        batch.create_index("ix_users_mtr_id", ["mtr_id"], unique=True)

    member_level = bind.scalar(sa.text("SELECT id FROM access_levels WHERE name = 'Member'"))
    users = {
        row.id: row
        for row in bind.execute(sa.text("SELECT id, email, full_name FROM users"))
    }
    by_email = {u.email.lower(): uid for uid, u in users.items() if u.email}
    profiles = list(bind.execute(sa.text(
        f"SELECT id, user_id, full_name, email, {', '.join(FIELDS)} FROM member_profiles ORDER BY id"
    )).mappings())
    owned = {p["user_id"] for p in profiles if p["user_id"] is not None}

    mapping: dict[int, int] = {}
    now = datetime.now(timezone.utc)
    for p in profiles:
        email = (p["email"] or "").strip().lower() or None
        notes = [p["review_note"]]
        uid = p["user_id"]
        if uid is None and email and email in by_email and by_email[email] not in owned:
            uid = by_email[email]  # an account for this email that had no roster row
            owned.add(uid)
        if uid is None:
            if email and email in by_email:
                notes.append(f"Roster email {email} belongs to another account.")
                email = None
            name = (p["full_name"] or "").strip() or p["mtr_id"] or f"Member #{p['id']}"
            bind.execute(sa.text(
                "INSERT INTO users (email, full_name, hashed_password, access_level_id, is_active, created_at)"
                " VALUES (:email, :name, :pw, :level, :active, :now)"
            ), {"email": email, "name": name, "pw": UNUSABLE_PASSWORD, "level": member_level,
                "active": True, "now": now})
            uid = bind.scalar(sa.text("SELECT max(id) FROM users"))
            if email:
                by_email[email] = uid
        else:
            account = users.get(uid)
            roster_name = (p["full_name"] or "").strip()
            if account is not None and roster_name and roster_name != account.full_name:
                notes.append(f"Roster name: {roster_name}")
            if account is not None and not account.email and email and email not in by_email:
                bind.execute(sa.text("UPDATE users SET email = :e WHERE id = :id"), {"e": email, "id": uid})
                by_email[email] = uid
        values = {f: p[f] for f in FIELDS}
        values["review_note"] = _note(*notes)
        bind.execute(
            sa.text(f"UPDATE users SET {', '.join(f'{f} = :{f}' for f in FIELDS)} WHERE id = :uid"),
            {**values, "uid": uid},
        )
        mapping[p["id"]] = uid

    _repoint(bind, mapping, "users")

    op.drop_table("member_profiles")  # its indexes go with it


def downgrade() -> None:
    """Split the roster back out: one member_profiles row per account that
    carries any roster data or is referenced as a member. Unclaimed accounts
    stay accounts (the split can't tell which ones the old schema lacked)."""
    bind = op.get_bind()
    op.create_table(
        "member_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("full_name", sa.String(255), nullable=True),
        sa.Column("email", sa.String(255), nullable=True),
        *[c.copy() for c in ROSTER_COLUMNS],
    )
    op.create_index("ix_member_profiles_user_id", "member_profiles", ["user_id"], unique=True)
    op.create_index("ix_member_profiles_mtr_id", "member_profiles", ["mtr_id"], unique=True)
    op.create_index("ix_member_profiles_email", "member_profiles", ["email"])

    referenced = set()
    for table, _ in MEMBER_REFS:
        referenced |= {r[0] for r in bind.execute(sa.text(f"SELECT member_id FROM {table} WHERE member_id IS NOT NULL"))}
    mapping: dict[int, int] = {}
    rows = bind.execute(sa.text(f"SELECT id, full_name, email, {', '.join(FIELDS)} FROM users ORDER BY id")).mappings()
    for u in rows:
        if u["id"] not in referenced and not any(u[f] is not None for f in FIELDS):
            continue
        bind.execute(sa.text(
            f"INSERT INTO member_profiles (user_id, full_name, email, {', '.join(FIELDS)})"
            f" VALUES (:uid, :full_name, :email, {', '.join(':' + f for f in FIELDS)})"
        ), {**{f: u[f] for f in FIELDS}, "uid": u["id"], "full_name": u["full_name"], "email": u["email"]})
        mapping[u["id"]] = bind.scalar(sa.text("SELECT id FROM member_profiles WHERE user_id = :u"), {"u": u["id"]})

    _repoint(bind, mapping, "member_profiles")

    with op.batch_alter_table("users") as batch:
        batch.drop_index("ix_users_mtr_id")
        for f in FIELDS:
            batch.drop_column(f)
    # users.email stays nullable: email-less accounts created by the upgrade
    # would violate NOT NULL, and nothing in the old code relied on it.
