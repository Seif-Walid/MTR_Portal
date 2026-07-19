"""Org-tree endpoint and user management under the access ladder: editing
accounts is the users.manage privilege (top level only in the test ladder);
everyone else gets a view of their own subtree, nothing more."""


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


def test_team_lead_sees_own_subtree_rooted_at_self_view_only(login, org):
    tree = login("team_lead").get("/api/team/tree").json()
    assert len(tree) == 1
    root = tree[0]
    assert root["id"] == org["team_lead"].id
    child_emails = {c["email"] for c in root["children"]}
    assert child_emails == {"stud@t.local", "comp@t.local"}
    # user management is a privilege now, not a subtree perk — without
    # users.manage the whole view is read-only
    assert not any(c["can_manage"] for c in root["children"])


def test_member_tree_is_just_self(login, org):
    tree = login("student").get("/api/team/tree").json()
    assert len(tree) == 1 and tree[0]["children"] == []
    assert tree[0]["can_manage"] is False


def test_tree_shows_effective_levels(login, org):
    tree = login("admin").get("/api/team/tree").json()
    by_email = {}

    def walk(nodes):
        for n in nodes:
            by_email[n["email"]] = n
            walk(n["children"])
    walk(tree)
    assert by_email["ceo@t.local"]["level"] == "Exec"
    assert by_email["stud@t.local"]["level"] == "Requester"


def test_user_management_requires_the_privilege(login, org):
    # a Lead (no users.manage) can neither create nor edit accounts
    assert login("team_lead").post(
        "/api/users",
        json={"email": "newkid@t.local", "full_name": "New Kid",
              "password": "password123", "manager_id": org["team_lead"].id},
    ).status_code == 403
    assert login("team_lead").patch(
        f"/api/users/{org['student'].id}", json={"full_name": "Nope"}
    ).status_code == 403
    # neither can an Exec — users.manage is top-level-only in the test ladder
    assert login("ceo").patch(
        f"/api/users/{org['mech_emp'].id}", json={"full_name": "Nope"}
    ).status_code == 403
    # members obviously can't either
    assert login("student").post(
        "/api/users",
        json={"email": "z@t.local", "full_name": "Z", "password": "password123",
              "manager_id": org["student"].id},
    ).status_code == 403


def test_admin_creates_edits_and_moves_users(login, org):
    admin = login("admin")
    r = admin.post(
        "/api/users",
        json={"email": "newkid@t.local", "full_name": "New Kid",
              "password": "password123", "manager_id": org["team_lead"].id},
    )
    assert r.status_code == 201, r.text
    assert r.json()["manager_id"] == org["team_lead"].id
    # a fresh account with no override and no seat is a guest (bottom level)
    assert r.json()["effective_level"] == "Guest"

    assert admin.patch(
        f"/api/users/{org['student'].id}", json={"full_name": "Salma Renamed"}
    ).status_code == 200
    # reparent across branches
    assert admin.patch(
        f"/api/users/{org['student'].id}", json={"manager_id": org["comp_member"].id}
    ).status_code == 200
    # cycles still rejected
    assert admin.patch(
        f"/api/users/{org['team_lead'].id}", json={"manager_id": org["student"].id}
    ).status_code == 400


def test_last_top_override_is_protected(login, org):
    admin = login("admin")
    levels = {l["name"]: l["id"] for l in admin.get("/api/access/levels").json()}
    # demoting or clearing the only top-level override is refused
    assert admin.patch(
        f"/api/users/{org['admin'].id}", json={"access_level_id": levels["Member"]}
    ).status_code == 400
    assert admin.patch(
        f"/api/users/{org['admin'].id}", json={"clear_access_level": True}
    ).status_code == 400
    # so is deactivating that account
    r = admin.patch(f"/api/users/{org['ceo'].id}", json={"access_level_id": levels["Admin"]})
    assert r.status_code == 200, r.text
    # now that a second anchor exists, the original can step down
    assert admin.patch(
        f"/api/users/{org['admin'].id}", json={"access_level_id": levels["Member"]}
    ).status_code == 200
