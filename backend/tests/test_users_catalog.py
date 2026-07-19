"""The catalogs the management UI picks from: the access ladder (any signed-in
user — pickers need it) and the fixed privilege vocabulary that feeds the
level editor."""


def test_levels_are_readable_by_anyone_signed_in(login, org):
    levels = login("student").get("/api/access/levels").json()
    names = [l["name"] for l in levels]
    assert names == ["Admin", "Exec", "Lead", "Staff", "Requester", "Member", "Guest"]
    assert levels[0]["is_top"] is True and levels[0]["rank"] == 1


def test_privilege_vocabulary_is_served_not_hardcoded(login, org):
    privs = login("student").get("/api/access/privileges").json()
    keys = {p["key"] for p in privs}
    assert {"inventory.view", "competitions.create", "org.edit", "users.manage"} <= keys
    assert all(p["label"] for p in privs)


def test_level_editor_is_users_manage_gated(login, org):
    levels = {l["name"]: l for l in login("admin").get("/api/access/levels").json()}
    # a non-manager can't create/edit/delete levels
    assert login("ceo").post("/api/access/levels", json={"name": "X"}).status_code == 403
    assert login("ceo").patch(
        f"/api/access/levels/{levels['Member']['id']}", json={"name": "X"}
    ).status_code == 403
    # the admin can, and the top level itself is protected
    assert login("admin").patch(
        f"/api/access/levels/{levels['Admin']['id']}", json={"privileges": []}
    ).status_code == 400
    assert login("admin").delete(f"/api/access/levels/{levels['Admin']['id']}").status_code == 400
    r = login("admin").post("/api/access/levels", json={"name": "Alumni", "privileges": ["org.view"]})
    assert r.status_code == 201
    assert r.json()["rank"] == 8  # appended at the bottom
    assert login("admin").delete(f"/api/access/levels/{r.json()['id']}").status_code == 204
