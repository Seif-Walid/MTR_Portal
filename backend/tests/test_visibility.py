"""Rule 3: a user sees their own tasks plus everything in their subtree."""

from tests.conftest import make_task


def visible_ids(login, who: str) -> set[int]:
    r = login(who).get("/api/tasks", params={"view": "all"})
    assert r.status_code == 200
    return {t["id"] for t in r.json()}


def test_subtree_visibility(login, org):
    t_mech = make_task(login, "mech_lead", org, "mech_emp", "mech work")
    t_sw = make_task(login, "cto", org, "sw_emp", "sw work")
    t_student = make_task(login, "team_lead", org, "student", "research")

    # CTO sees the mech task (assigned by a sub-lead, two levels down) + sw task
    cto_sees = visible_ids(login, "cto")
    assert t_mech["id"] in cto_sees and t_sw["id"] in cto_sees
    assert t_student["id"] not in cto_sees  # other branch

    # mech_lead doesn't see software tasks
    mech_sees = visible_ids(login, "mech_lead")
    assert t_mech["id"] in mech_sees
    assert t_sw["id"] not in mech_sees

    # CEO sees everything
    ceo_sees = visible_ids(login, "ceo")
    assert {t_mech["id"], t_sw["id"], t_student["id"]} <= ceo_sees

    # PM sees the student's task through the team lead
    assert t_student["id"] in visible_ids(login, "pm")


def test_leaf_sees_only_own_tasks(login, org):
    t_mine = make_task(login, "cto", org, "sw_emp", "mine")
    t_other = make_task(login, "mech_lead", org, "mech_emp", "not mine")
    sw_sees = visible_ids(login, "sw_emp")
    assert t_mine["id"] in sw_sees
    assert t_other["id"] not in sw_sees


def test_task_detail_denied_outside_subtree_as_404(login, org):
    t = make_task(login, "mech_lead", org, "mech_emp")
    r = login("cfo").get(f"/api/tasks/{t['id']}")
    assert r.status_code == 404  # existence not leaked
    assert login("cto").get(f"/api/tasks/{t['id']}").status_code == 200


def test_team_view_scopes_to_subtree(login, org):
    make_task(login, "mech_lead", org, "mech_emp")
    r = login("cto").get("/api/team")
    members = {m["user"]["id"]: m for m in r.json()}
    assert set(members) == {org[k].id for k in ("sw_emp", "mech_lead", "elec_lead", "mech_emp")}
    assert members[org["mech_emp"].id]["total_tasks"] == 1
    assert members[org["mech_emp"].id]["is_direct_report"] is False

    # leaf users have no team
    assert login("student").get("/api/team").json() == []


def test_drill_down_into_subordinate_tasks(login, org):
    t = make_task(login, "mech_lead", org, "mech_emp")
    r = login("cto").get("/api/tasks", params={"view": "all", "assignee_id": org["mech_emp"].id})
    assert [x["id"] for x in r.json()] == [t["id"]]
    # cfo gets nothing for that assignee
    r = login("cfo").get("/api/tasks", params={"view": "all", "assignee_id": org["mech_emp"].id})
    assert r.json() == []
