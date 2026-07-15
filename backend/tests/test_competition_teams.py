"""Competition nesting (category → team → members) and team-lead scoping."""


def _comp(login, who="cto", name="C"):
    return login(who).post("/api/competitions", json={"name": name})


def _category(login, cid, who="cto", name="Senior"):
    return login(who).post(f"/api/competitions/{cid}/categories", json={"name": name})


def _team(login, cat_id, who="cto", name="Team A", **over):
    body = {"name": name}
    body.update(over)
    return login(who).post(f"/api/competitions/categories/{cat_id}/teams", json=body)


def test_full_nesting(login, org):
    cid = _comp(login, "cto").json()["id"]
    cat = _category(login, cid).json()
    team = _team(login, cat["id"], lead_id=org["team_lead"].id).json()
    assert team["lead"]["id"] == org["team_lead"].id

    login("cto").post(f"/api/competitions/teams/{team['id']}/members", json={"user_id": org["student"].id})
    r = login("cto").post(f"/api/competitions/teams/{team['id']}/members", json={"user_id": org["comp_member"].id})
    assert {m["user"]["id"] for m in r.json()["members"]} == {org["student"].id, org["comp_member"].id}

    detail = login("cto").get(f"/api/competitions/{cid}").json()
    assert detail["category_count"] == 1 and detail["team_count"] == 1 and detail["member_count"] == 2
    assert detail["categories"][0]["teams"][0]["name"] == "Team A"


def test_team_lead_manages_only_their_team(login, org):
    cid = _comp(login, "cto").json()["id"]
    cat = _category(login, cid).json()
    # the student is the scoped lead of Team A (a non-staff member leading a team)
    team_a = _team(login, cat["id"], name="A", lead_id=org["student"].id).json()
    team_b = _team(login, cat["id"], name="B").json()

    # lead of A may add members to A
    assert login("student").post(
        f"/api/competitions/teams/{team_a['id']}/members", json={"user_id": org["comp_member"].id}
    ).status_code == 201
    # but not to team B, and not to the competition structure
    assert login("student").post(
        f"/api/competitions/teams/{team_b['id']}/members", json={"user_id": org["comp_member"].id}
    ).status_code == 403
    assert login("student").post(
        f"/api/competitions/{cid}/categories", json={"name": "X"}
    ).status_code == 403


def test_can_manage_flags_reflect_scope(login, org):
    cid = _comp(login, "cto").json()["id"]
    cat = _category(login, cid).json()
    _team(login, cat["id"], name="A", lead_id=org["student"].id)
    # the student sees can_manage_members only on their own team
    detail = login("student").get(f"/api/competitions/{cid}").json()
    team = detail["categories"][0]["teams"][0]
    assert detail["can_manage"] is False  # not a PM/high-staff
    assert team["can_manage_members"] is True  # but leads this team


def test_delete_competition_cascades(login, org):
    cid = _comp(login, "cto").json()["id"]
    cat = _category(login, cid).json()
    _team(login, cat["id"])
    assert login("cto").delete(f"/api/competitions/{cid}").status_code == 204
    assert login("cto").get(f"/api/competitions/{cid}").status_code == 404
