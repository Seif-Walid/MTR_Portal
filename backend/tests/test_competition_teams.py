"""Competition category, single team (name + lead), members, and the high-staff gate."""


def _category(login, who="cto", name="Senior"):
    return login(who).post("/api/competitions/categories", json={"name": name})


def _competition(login, who="cto", name="RoboCup 2026", **over):
    body = {"name": name}
    body.update(over)
    return login(who).post("/api/competitions", json=body)


def test_only_high_staff_can_manage(login, org):
    # CTO (leadership) can; a plain Employee and non-staff cannot
    assert _competition(login, "cto").status_code == 201
    assert _competition(login, "sw_emp", name="X").status_code == 403  # employee = not high staff
    assert _competition(login, "student", name="Y").status_code == 403


def test_categories_crud(login, org):
    assert _category(login, "cto", "Senior").status_code == 201
    assert _category(login, "cto", "Senior").status_code == 409  # duplicate
    assert _category(login, "sw_emp", "Junior").status_code == 403  # employee blocked
    assert "Senior" in {c["name"] for c in login("cto").get("/api/competitions/categories").json()}


def test_competition_carries_team_fields(login, org):
    cat_id = _category(login, "cto", "Senior").json()["id"]
    comp = _competition(
        login, "cto", category_id=cat_id, team_name="Robotics A", team_lead_id=org["team_lead"].id
    ).json()
    assert comp["category"]["name"] == "Senior"
    assert comp["team_name"] == "Robotics A"
    assert comp["team_lead"]["id"] == org["team_lead"].id
    detail = login("cto").get(f"/api/competitions/{comp['id']}").json()
    assert detail["team_name"] == "Robotics A"
    assert detail["members"] == []


def test_members_add_remove(login, org):
    comp_id = _competition(login, "cto").json()["id"]
    login("cto").post(f"/api/competitions/{comp_id}/members", json={"user_id": org["student"].id})
    r = login("cto").post(
        f"/api/competitions/{comp_id}/members", json={"user_id": org["comp_member"].id}
    )
    ids = {m["user"]["id"] for m in r.json()["members"]}
    assert ids == {org["student"].id, org["comp_member"].id}

    # idempotent
    r = login("cto").post(f"/api/competitions/{comp_id}/members", json={"user_id": org["student"].id})
    assert len(r.json()["members"]) == 2

    d = login("cto").get(f"/api/competitions/{comp_id}").json()
    assert d["member_count"] == 2

    assert login("cto").delete(
        f"/api/competitions/{comp_id}/members/{org['student'].id}"
    ).status_code == 204
    assert login("cto").get(f"/api/competitions/{comp_id}").json()["member_count"] == 1


def test_clear_team_lead(login, org):
    comp_id = _competition(login, "cto", team_lead_id=org["team_lead"].id).json()["id"]
    r = login("cto").patch(f"/api/competitions/{comp_id}", json={"clear_team_lead": True})
    assert r.status_code == 200 and r.json()["team_lead"] is None


def test_delete_cascades_members(login, org):
    comp_id = _competition(login, "cto").json()["id"]
    login("cto").post(f"/api/competitions/{comp_id}/members", json={"user_id": org["student"].id})
    assert login("cto").delete(f"/api/competitions/{comp_id}").status_code == 204
    assert login("cto").get(f"/api/competitions/{comp_id}").status_code == 404


def test_member_management_blocked_for_non_high_staff(login, org):
    comp_id = _competition(login, "cto").json()["id"]
    assert login("sw_emp").post(
        f"/api/competitions/{comp_id}/members", json={"user_id": org["student"].id}
    ).status_code == 403
