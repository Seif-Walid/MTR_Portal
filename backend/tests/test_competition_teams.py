"""Competition nesting (category -> team -> members) and team-role scoping."""

from tests.conftest import ensure_position, seat_role, setup_role_templates


def _comp(login, who="cto", name="C"):
    """Creates a competition and seats the creator as its managing PM —
    nothing auto-seats anymore, the appointment is explicit."""
    admin = login("admin")
    setup_role_templates(admin, pm=True)
    body = {"name": name}
    if not admin.get("/api/org/roles/root").json()["root_position_id"]:
        body["role_root_position_id"] = ensure_position(admin)
    r = login(who).post("/api/competitions", json=body)
    if r.status_code == 201:
        me = login(who).get("/api/auth/me").json()
        seat_role(admin, r.json(), [me["id"]])
    return r


def _category(login, cid, who="cto", name="Senior"):
    return login(who).post(f"/api/competitions/{cid}/categories", json={"name": name})


def _team(login, cat_id, who="cto", name="Team A"):
    admin = login("admin")
    setup_role_templates(admin, team_lead=True)
    body = {"name": name}
    if not admin.get("/api/org/roles/root").json()["root_position_id"]:
        body["role_root_position_id"] = ensure_position(admin)
    return login(who).post(f"/api/competitions/categories/{cat_id}/teams", json=body)


def _appoint_lead(login, team: dict, user_id: int, who="cto") -> None:
    pos_id = team["roles"][0]["position_id"]
    r = login(who).put(f"/api/org/roles/positions/{pos_id}/occupants", json={"user_ids": [user_id]})
    assert r.status_code == 200, r.text


def test_full_nesting(login, org):
    cid = _comp(login, "cto").json()["id"]
    cat = _category(login, cid).json()
    team = _team(login, cat["id"]).json()
    _appoint_lead(login, team, org["team_lead"].id)

    login("cto").post(f"/api/competitions/teams/{team['id']}/members", json={"user_id": org["student"].id})
    r = login("cto").post(f"/api/competitions/teams/{team['id']}/members", json={"user_id": org["comp_member"].id})
    assert {m["user"]["id"] for m in r.json()["members"]} == {org["student"].id, org["comp_member"].id}

    detail = login("cto").get(f"/api/competitions/{cid}").json()
    assert detail["category_count"] == 1 and detail["team_count"] == 1 and detail["member_count"] == 2
    team_out = detail["categories"][0]["teams"][0]
    assert team_out["name"] == "Team A"
    assert team_out["roles"][0]["occupants"][0]["id"] == org["team_lead"].id


def test_team_lead_manages_only_their_team(login, org):
    cid = _comp(login, "cto").json()["id"]
    cat = _category(login, cid).json()
    # the student is the scoped lead of Team A (a non-staff member leading a team)
    team_a = _team(login, cat["id"], name="A").json()
    team_b = _team(login, cat["id"], name="B").json()
    _appoint_lead(login, team_a, org["student"].id)

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
    team_a = _team(login, cat["id"], name="A").json()
    _appoint_lead(login, team_a, org["student"].id)
    # the student sees can_manage_members only on their own team
    detail = login("student").get(f"/api/competitions/{cid}").json()
    team = detail["categories"][0]["teams"][0]
    assert detail["can_manage"] is False  # not a manager/high-staff of the competition
    assert team["can_manage_members"] is True  # but leads this team
