"""Org-tree endpoint and hierarchy management scoped to a manager's subtree."""


def _emails(nodes):
    """Flatten a tree into a set of emails."""
    out = set()
    for n in nodes:
        out.add(n["email"])
        out |= _emails(n["children"])
    return out


def test_admin_sees_whole_org_tree(login, org):
    tree = login("admin").get("/api/team/tree").json()
    all_emails = _emails(tree)
    # everyone is reachable from the roots
    assert {"ceo@t.local", "cto@t.local", "stud@t.local", "comp@t.local"} <= all_emails


def test_team_lead_sees_own_subtree_rooted_at_self(login, org):
    tree = login("team_lead").get("/api/team/tree").json()
    assert len(tree) == 1
    root = tree[0]
    assert root["id"] == org["team_lead"].id
    assert root["can_manage"] is False  # can't manage self
    child_emails = {c["email"] for c in root["children"]}
    assert child_emails == {"stud@t.local", "comp@t.local"}
    assert all(c["can_manage"] for c in root["children"])  # can manage reports


def test_non_staff_tree_is_just_self(login, org):
    tree = login("student").get("/api/team/tree").json()
    assert len(tree) == 1 and tree[0]["children"] == []
    assert tree[0]["can_manage"] is False


def test_team_lead_adds_person_under_self(login, org):
    r = login("team_lead").post(
        "/api/users",
        json={
            "email": "newkid@t.local",
            "full_name": "New Kid",
            "password": "password123",
            "roles": ["student"],
            "manager_id": org["team_lead"].id,
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["manager_id"] == org["team_lead"].id


def test_team_lead_cannot_add_outside_subtree_or_grant_admin(login, org):
    # under someone outside the subtree
    r = login("team_lead").post(
        "/api/users",
        json={
            "email": "x@t.local", "full_name": "X", "password": "password123",
            "roles": ["employee"], "manager_id": org["cto"].id,
        },
    )
    assert r.status_code == 403
    # granting admin
    r = login("team_lead").post(
        "/api/users",
        json={
            "email": "y@t.local", "full_name": "Y", "password": "password123",
            "roles": ["admin"], "manager_id": org["team_lead"].id,
        },
    )
    assert r.status_code == 403


def test_team_lead_edits_within_but_not_outside_subtree(login, org):
    # edit a report → ok
    r = login("team_lead").patch(
        f"/api/users/{org['student'].id}", json={"full_name": "Salma Renamed"}
    )
    assert r.status_code == 200, r.text
    # edit someone outside the subtree → 403
    assert login("team_lead").patch(
        f"/api/users/{org['cto'].id}", json={"full_name": "Nope"}
    ).status_code == 403


def test_team_lead_reparent_rules(login, org):
    # move student under comp_member (both in subtree) → ok
    r = login("team_lead").patch(
        f"/api/users/{org['student'].id}", json={"manager_id": org["comp_member"].id}
    )
    assert r.status_code == 200, r.text
    # detaching from the tree is admin-only
    assert login("team_lead").patch(
        f"/api/users/{org['comp_member'].id}", json={"clear_manager": True}
    ).status_code == 403
    # granting admin via edit → 403
    assert login("team_lead").patch(
        f"/api/users/{org['comp_member'].id}", json={"roles": ["admin"]}
    ).status_code == 403


def test_non_staff_cannot_manage_users(login, org):
    assert login("student").post(
        "/api/users",
        json={"email": "z@t.local", "full_name": "Z", "password": "password123",
              "roles": ["student"], "manager_id": org["student"].id},
    ).status_code == 403


def test_ceo_manages_whole_org_but_not_admin_role(login, org):
    tree = login("ceo").get("/api/team/tree").json()
    emails = _emails(tree)
    # CEO sees the whole org, minus the technical admin account
    assert {"cto@t.local", "stud@t.local", "memp@t.local"} <= emails
    assert "admin@t.local" not in emails
    # CEO can edit someone in another branch (mech_emp is under cto → mech_lead)
    assert login("ceo").patch(
        f"/api/users/{org['mech_emp'].id}", json={"full_name": "Renamed"}
    ).status_code == 200
    # CEO can add a person under anyone in the org
    assert login("ceo").post(
        "/api/users",
        json={"email": "n@t.local", "full_name": "N", "password": "password123",
              "roles": ["employee"], "manager_id": org["cto"].id},
    ).status_code == 201
    # ...but the admin role stays admin-only (per the original spec)
    assert login("ceo").post(
        "/api/users",
        json={"email": "a2@t.local", "full_name": "A2", "password": "password123",
              "roles": ["admin"], "manager_id": org["cto"].id},
    ).status_code == 403
