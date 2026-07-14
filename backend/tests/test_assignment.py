"""Rule 1: tasks flow down — only into the assigner's recursive subtree."""

from tests.conftest import make_task


def assign(login, org, assigner, assignee):
    return login(assigner).post(
        "/api/tasks", json={"title": "x", "assignee_id": org[assignee].id}
    )


def test_ceo_can_assign_anywhere_in_tree(login, org):
    assert assign(login, org, "ceo", "cto").status_code == 201
    assert assign(login, org, "ceo", "mech_emp").status_code == 201  # depth 3
    assert assign(login, org, "ceo", "student").status_code == 201  # other branch, depth 3


def test_manager_can_assign_recursive_subtree(login, org):
    # CTO reaches employees under their sub-leads, not just direct reports
    assert assign(login, org, "cto", "mech_lead").status_code == 201
    assert assign(login, org, "cto", "mech_emp").status_code == 201
    # PM reaches students two levels down
    assert assign(login, org, "pm", "student").status_code == 201


def test_cannot_assign_upward(login, org):
    assert assign(login, org, "sw_emp", "cto").status_code == 403
    assert assign(login, org, "cto", "ceo").status_code == 403
    assert assign(login, org, "student", "team_lead").status_code == 403


def test_cannot_assign_across_branches(login, org):
    assert assign(login, org, "mech_lead", "sw_emp").status_code == 403
    assert assign(login, org, "cfo", "mech_emp").status_code == 403
    assert assign(login, org, "media_mgr", "student").status_code == 403


def test_cannot_assign_to_self_or_peer(login, org):
    assert assign(login, org, "cto", "cto").status_code == 403
    assert assign(login, org, "cto", "cfo").status_code == 403  # sibling


def test_leaf_users_have_no_assignees(login, org):
    for who in ("sw_emp", "student", "comp_member"):
        r = login(who).get("/api/users/assignable")
        assert r.status_code == 200
        assert r.json() == []


def test_admin_bypasses_hierarchy(login, org):
    assert assign(login, org, "admin", "ceo").status_code == 201
    assert assign(login, org, "admin", "student").status_code == 201


def test_moving_a_user_moves_permissions_with_zero_config(login, org, db_session):
    # data-driven hierarchy: re-parent mech_emp under the CFO and permissions flip
    assert assign(login, org, "cfo", "mech_emp").status_code == 403
    org["mech_emp"].manager_id = org["cfo"].id
    db_session.commit()
    assert assign(login, org, "cfo", "mech_emp").status_code == 201
    assert assign(login, org, "mech_lead", "mech_emp").status_code == 403


def test_assignable_list_matches_subtree(login, org):
    r = login(cto := "cto").get("/api/users/assignable")
    ids = {u["id"] for u in r.json()}
    expected = {org[k].id for k in ("sw_emp", "mech_lead", "elec_lead", "mech_emp")}
    assert ids == expected


def test_hierarchy_move_admin_rejects_cycles(login, org):
    admin = login("admin")
    # making the CTO report to their own subordinate's subordinate is a cycle
    r = admin.patch(f"/api/users/{org['cto'].id}", json={"manager_id": org["mech_emp"].id})
    assert r.status_code == 400
    # self-management is a cycle too
    r = admin.patch(f"/api/users/{org['cto'].id}", json={"manager_id": org["cto"].id})
    assert r.status_code == 400
