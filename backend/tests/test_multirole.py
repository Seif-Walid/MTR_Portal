"""Effective power comes from one place: the access ladder. The /me payload
reports the resolved level + privileges, hierarchy reach stays structural
(the manager subtree), and user management is a privilege — not something a
job title or tree position ever implies."""

from tests.conftest import make_task


def test_me_reports_level_and_privileges(login, org):
    me = login("cto").get("/api/auth/me").json()
    assert me["level"]["name"] == "Lead"
    assert "tasks.assign" in me["privileges"]
    assert "users.manage" not in me["privileges"]
    assert me["has_team"] is True


def test_subtree_reach_covers_the_whole_branch(login, org):
    cto = login("cto")
    # direct reports
    r = cto.post("/api/tasks", json={"title": "sw", "assignee_ids": [org["sw_emp"].id]})
    assert r.status_code == 201
    # the whole technical branch, including mech employees below a sub-lead
    r = cto.post("/api/tasks", json={"title": "mech", "assignee_ids": [org["mech_emp"].id]})
    assert r.status_code == 201
    # reach does NOT extend outside the node's subtree
    r = cto.post("/api/tasks", json={"title": "fin", "assignee_ids": [org["fin_emp"].id]})
    assert r.status_code == 403


def test_task_visibility_covers_the_subtree(login, org):
    t_sw = make_task(login, "cto", org, "sw_emp")
    t_mech = make_task(login, "mech_lead", org, "mech_emp")
    seen = {t["id"] for t in login("cto").get("/api/tasks", params={"view": "all"}).json()}
    assert {t_sw["id"], t_mech["id"]} <= seen


def test_override_grants_power_without_a_seat(login, org):
    """The per-user override is a direct grant — bump a guest to Staff and
    they become a valid request recipient with no org seat involved."""
    fresh = login("admin").post("/api/users", json={
        "email": "advisor@t.local", "full_name": "Advisor", "password": "password123",
    }).json()
    # a guest (bottom rung) can't receive work requests
    r = login("cfo").post("/api/requests", json={"recipient_id": fresh["id"], "title": "help"})
    assert r.status_code == 400

    levels = {l["name"]: l["id"] for l in login("admin").get("/api/access/levels").json()}
    login("admin").patch(f"/api/users/{fresh['id']}", json={"access_level_id": levels["Staff"]})
    r = login("cfo").post("/api/requests", json={"recipient_id": fresh["id"], "title": "help"})
    assert r.status_code == 201


def test_user_management_is_a_privilege_not_a_title(login, org):
    # the top-level admin manages users...
    r = login("admin").get("/api/users")
    assert r.status_code == 200
    # ...but an Exec without users.manage does not, whatever their position
    assert login("ceo").get("/api/users").status_code == 403
