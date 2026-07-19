"""access ladder replaces builtin roles

Revision ID: e5a9c8b4d2f1
Revises: c4f1a7d92e6b
Create Date: 2026-07-19 12:00:00.000000

Replaces the hardcoded role catalog (roles/user_roles, RoleSlug) with the
data-driven access ladder: access_levels + access_level_id on users
(personal override), positions (what the seat confers) and role_templates
(what produced seats confer).

Data carried forward:
- the five preset levels are inserted (fresh ladders start identical),
- every user holding the 'admin' role slug gets a rank-1 (top) override, so
  nobody who could administrate before is locked out after,
- role templates with grants_management=1 map to the "Lead" level (whose
  privileges include competitions.manage_seated — the same authority), and
  their already-produced positions get the same level copied on.

Carried back on downgrade (best effort): the role catalog is recreated,
top-override users get the admin slug again, and templates whose level
includes competitions.manage_seated get grants_management=1.
"""
import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e5a9c8b4d2f1'
down_revision: Union[str, None] = 'c4f1a7d92e6b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NAMING_CONVENTION = {
    "fk": "fk_%(table_name)s_%(column_0_name)s",
}
FK_USERS_LEVEL = "fk_users_access_level_id"
FK_POSITIONS_LEVEL = "fk_positions_access_level_id"
FK_TEMPLATES_LEVEL = "fk_role_templates_access_level_id"

_ALL = [
    "inventory.view", "inventory.request", "inventory.approve", "inventory.edit",
    "competitions.view", "competitions.manage_seated", "competitions.create",
    "competitions.manage_any", "tasks.use", "tasks.assign", "org.view", "org.edit",
    "people.view", "users.manage", "audit.view", "sync.export", "sync.rebuild",
]
PRESETS = [
    (1, "Admin", sorted(_ALL)),
    (2, "Board", sorted(set(_ALL) - {"users.manage", "sync.rebuild"})),
    (3, "Lead", [
        "inventory.view", "inventory.request", "inventory.approve", "inventory.edit",
        "competitions.view", "competitions.manage_seated", "competitions.create",
        "tasks.use", "tasks.assign", "org.view", "people.view",
    ]),
    (4, "Member", [
        "inventory.view", "inventory.request",
        "competitions.view", "tasks.use", "org.view", "people.view",
    ]),
    (5, "Guest", []),
]


def upgrade() -> None:
    bind = op.get_bind()

    op.create_table(
        "access_levels",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("rank", sa.Integer(), nullable=False, unique=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("privileges", sa.Text(), nullable=False),
    )
    for rank, name, keys in PRESETS:
        bind.execute(
            sa.text("INSERT INTO access_levels (rank, name, privileges) VALUES (:r, :n, :p)"),
            {"r": rank, "n": name, "p": json.dumps(keys)},
        )
    top_id = bind.execute(
        sa.text("SELECT id FROM access_levels ORDER BY rank LIMIT 1")
    ).scalar_one()
    lead_id = bind.execute(
        sa.text("SELECT id FROM access_levels WHERE name = 'Lead'")
    ).scalar_one()

    with op.batch_alter_table("users", schema=None, naming_convention=NAMING_CONVENTION) as batch_op:
        batch_op.add_column(sa.Column("access_level_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            FK_USERS_LEVEL, "access_levels", ["access_level_id"], ["id"], ondelete="SET NULL"
        )
    # admins keep their power as a top-level override
    bind.execute(sa.text(
        "UPDATE users SET access_level_id = :top WHERE id IN ("
        " SELECT ur.user_id FROM user_roles ur JOIN roles r ON r.id = ur.role_id"
        " WHERE r.slug = 'admin')"
    ), {"top": top_id})

    with op.batch_alter_table("positions", schema=None, naming_convention=NAMING_CONVENTION) as batch_op:
        batch_op.add_column(sa.Column("access_level_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            FK_POSITIONS_LEVEL, "access_levels", ["access_level_id"], ["id"], ondelete="SET NULL"
        )

    with op.batch_alter_table("role_templates", schema=None, naming_convention=NAMING_CONVENTION) as batch_op:
        batch_op.add_column(sa.Column("access_level_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            FK_TEMPLATES_LEVEL, "access_levels", ["access_level_id"], ["id"], ondelete="SET NULL"
        )
    # grants_management templates conferred scoped management; the Lead level
    # is the preset that carries the same privilege
    bind.execute(sa.text(
        "UPDATE role_templates SET access_level_id = :lead WHERE grants_management = :yes"
    ), {"lead": lead_id, "yes": True})
    bind.execute(sa.text(
        "UPDATE positions SET access_level_id = ("
        " SELECT rt.access_level_id FROM role_templates rt WHERE rt.id = positions.role_template_id)"
        " WHERE role_template_id IS NOT NULL"
    ))
    with op.batch_alter_table("role_templates", schema=None, naming_convention=NAMING_CONVENTION) as batch_op:
        batch_op.drop_column("grants_management")
        batch_op.drop_column("auto_assign_creator")

    op.drop_table("user_roles")
    op.drop_table("roles")


def downgrade() -> None:
    bind = op.get_bind()

    op.create_table(
        "roles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("slug", sa.String(length=50), nullable=False, unique=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("is_staff", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "user_roles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role_id", sa.Integer(), sa.ForeignKey("roles.id", ondelete="CASCADE"), nullable=False),
        sa.UniqueConstraint("user_id", "role_id"),
    )
    slugs = [
        ("admin", "Technical Admin", False), ("ceo", "CEO", True), ("cto", "CTO", True),
        ("cfo", "CFO", True), ("software_lead", "Software Lead", True),
        ("mechanical_lead", "Mechanical Lead", True), ("electrical_lead", "Electrical Lead", True),
        ("media_manager", "Media Manager", True), ("project_manager", "Project Manager", True),
        ("team_lead", "Team Lead", True), ("employee", "Employee", True),
        ("student", "Student", False), ("competition_member", "Competition Member", False),
    ]
    for slug, name, is_staff in slugs:
        bind.execute(
            sa.text("INSERT INTO roles (slug, name, is_staff) VALUES (:s, :n, :st)"),
            {"s": slug, "n": name, "st": is_staff},
        )
    top_id = bind.execute(
        sa.text("SELECT id FROM access_levels ORDER BY rank LIMIT 1")
    ).scalar()
    if top_id is not None:
        bind.execute(sa.text(
            "INSERT INTO user_roles (user_id, role_id)"
            " SELECT u.id, (SELECT id FROM roles WHERE slug = 'admin') FROM users u"
            " WHERE u.access_level_id = :top"
        ), {"top": top_id})

    with op.batch_alter_table("role_templates", schema=None, naming_convention=NAMING_CONVENTION) as batch_op:
        batch_op.add_column(sa.Column("grants_management", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column("auto_assign_creator", sa.Boolean(), nullable=False, server_default=sa.false()))
    bind.execute(sa.text(
        "UPDATE role_templates SET grants_management = :yes WHERE access_level_id IN ("
        " SELECT id FROM access_levels WHERE privileges LIKE '%competitions.manage_seated%')"
    ), {"yes": True})
    with op.batch_alter_table("role_templates", schema=None, naming_convention=NAMING_CONVENTION) as batch_op:
        batch_op.drop_constraint(FK_TEMPLATES_LEVEL, type_="foreignkey")
        batch_op.drop_column("access_level_id")

    with op.batch_alter_table("positions", schema=None, naming_convention=NAMING_CONVENTION) as batch_op:
        batch_op.drop_constraint(FK_POSITIONS_LEVEL, type_="foreignkey")
        batch_op.drop_column("access_level_id")

    with op.batch_alter_table("users", schema=None, naming_convention=NAMING_CONVENTION) as batch_op:
        batch_op.drop_constraint(FK_USERS_LEVEL, type_="foreignkey")
        batch_op.drop_column("access_level_id")

    op.drop_table("access_levels")
