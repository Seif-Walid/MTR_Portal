"""Editing the Hall-of-Fame fields (event awards, per-team award, per-member
role) through the events API, and that the public endpoint reflects them."""

from tests.test_event_teams import _category, _comp, _team


def _setup(login, org):
    cid = _comp(login, "cto").json()["id"]
    cat = _category(login, cid).json()
    team = _team(login, cat["id"]).json()
    login("cto").post(
        f"/api/events/teams/{team['id']}/members", json={"user_id": org["student"].id}
    )
    return cid, team["id"], org["student"].id


def test_edit_event_awards(login, org):
    cid, _, _ = _setup(login, org)
    r = login("cto").patch(
        f"/api/events/{cid}", json={"awards": ["🥇 1st Place — Sumo", "Best Design"]}
    )
    assert r.status_code == 200, r.text
    assert r.json()["awards"] == ["🥇 1st Place — Sumo", "Best Design"]

    # clear
    r = login("cto").patch(f"/api/events/{cid}", json={"clear_awards": True})
    assert r.json()["awards"] is None


def test_edit_team_award(login, org):
    cid, team_id, _ = _setup(login, org)
    r = login("cto").patch(f"/api/events/teams/{team_id}", json={"award": "🥈 2nd Place"})
    assert r.status_code == 200, r.text
    assert r.json()["award"] == "🥈 2nd Place"

    r = login("cto").patch(f"/api/events/teams/{team_id}", json={"clear_award": True})
    assert r.json()["award"] is None


def test_edit_member_role(login, org):
    cid, team_id, uid = _setup(login, org)
    r = login("cto").patch(
        f"/api/events/teams/{team_id}/members/{uid}", json={"role": "Electrical"}
    )
    assert r.status_code == 200, r.text
    member = next(m for m in r.json()["members"] if m["user"]["id"] == uid)
    assert member["role"] == "Electrical"

    r = login("cto").patch(
        f"/api/events/teams/{team_id}/members/{uid}", json={"clear_role": True}
    )
    member = next(m for m in r.json()["members"] if m["user"]["id"] == uid)
    assert member["role"] is None


def test_edits_surface_in_public_hall_of_fame(login, org, client):
    """The public endpoint (archived competition events) reflects the edits."""
    cid, team_id, uid = _setup(login, org)
    login("cto").patch(f"/api/events/{cid}", json={"awards": ["🏆 Champions"]})
    login("cto").patch(f"/api/events/teams/{team_id}", json={"award": "🥇 1st Place"})
    login("cto").patch(f"/api/events/teams/{team_id}/members/{uid}", json={"role": "Software"})
    # Hall of Fame shows archived competitions only.
    login("cto").patch(f"/api/events/{cid}", json={"status": "archived"})

    data = client.get("/api/public/hall-of-fame").json()
    rec = next((r for r in data if r["id"] == str(cid)), None)
    assert rec is not None, "archived event should appear in the public feed"
    assert rec["awards"] == ["🏆 Champions"]
    grp = rec["groups"][0]
    assert grp["award"] == "🥇 1st Place"
    assert grp["members"][0]["role"] == "Software"
