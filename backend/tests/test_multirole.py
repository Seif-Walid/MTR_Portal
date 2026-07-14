"""Multi-role users: effective permissions are the union of all held roles.
The seeded 'cto' user holds CTO + Software Lead simultaneously."""

from tests.conftest import make_task


def test_me_reports_union_of_roles(login, org):
    me = login("cto").get("/api/auth/me").json()
    assert {r["slug"] for r in me["roles"]} == {"cto", "software_lead"}
    assert me["is_staff"] is True
    assert me["has_team"] is True


def test_multirole_reach_covers_both_hats(login, org):
    cto = login("cto")
    # Software Lead hat: direct software employees
    r = cto.post("/api/tasks", json={"title": "sw", "assignee_id": org["sw_emp"].id})
    assert r.status_code == 201
    # CTO hat: the whole technical branch, including mech employees below a sub-lead
    r = cto.post("/api/tasks", json={"title": "mech", "assignee_id": org["mech_emp"].id})
    assert r.status_code == 201
    # union does NOT extend outside the node's subtree
    r = cto.post("/api/tasks", json={"title": "fin", "assignee_id": org["fin_emp"].id})
    assert r.status_code == 403


def test_multirole_visibility_is_union(login, org):
    t_sw = make_task(login, "cto", org, "sw_emp")
    t_mech = make_task(login, "mech_lead", org, "mech_emp")
    seen = {t["id"] for t in login("cto").get("/api/tasks", params={"view": "all"}).json()}
    assert {t_sw["id"], t_mech["id"]} <= seen


def test_staff_flag_unions_across_roles(login, org, db_session):
    """A student who is also a team lead becomes a valid request recipient."""
    from sqlalchemy import select

    from app.domains.users.models import Role, RoleSlug, UserRole

    student = org["student"]
    # student alone: not staff -> request rejected (fin_emp is outside their subtree)
    r = login("fin_emp").post(
        "/api/requests", json={"recipient_id": student.id, "title": "help"}
    )
    assert r.status_code == 400

    tl_role = db_session.scalar(select(Role).where(Role.slug == RoleSlug.TEAM_LEAD))
    db_session.add(UserRole(user_id=student.id, role_id=tl_role.id))
    db_session.commit()
    db_session.expire(student)  # shared test session caches the roles relationship

    r = login("fin_emp").post(
        "/api/requests", json={"recipient_id": student.id, "title": "help"}
    )
    assert r.status_code == 201


def test_admin_role_is_separate_from_hierarchy(login, org):
    # admin manages users...
    r = login("admin").get("/api/users")
    assert r.status_code == 200
    # ...but hierarchy roles don't grant user management, even for the CEO
    assert login("ceo").get("/api/users").status_code == 403
