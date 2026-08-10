"""The public archive: archiving an event pulls its tasks out of the active
lists and into a per-viewer record of what each participant did."""

from tests.test_event_teams import _category, _comp, _team


def _team_with_members(login, org, member_keys, who="cto"):
    cid = _comp(login, who).json()["id"]
    cat = _category(login, cid).json()
    team = _team(login, cat["id"], who=who).json()
    for k in member_keys:
        r = login(who).post(f"/api/events/teams/{team['id']}/members", json={"user_id": org[k].id})
        assert r.status_code == 201, r.text
    return cid, team


def _assign_team_task(login, team, who="cto", visible=True, title="job"):
    r = login(who).post(
        "/api/tasks",
        json={"title": title, "event_team_id": team["id"], "team_visible": visible},
    )
    assert r.status_code == 201, r.text
    return r.json()


def _approve(login, task, assignee_key, assigner="cto"):
    login(assignee_key).patch(f"/api/tasks/{task['id']}/status", json={"status": "in_progress"})
    login(assignee_key).patch(f"/api/tasks/{task['id']}/status", json={"status": "submitted"})
    r = login(assigner).patch(f"/api/tasks/{task['id']}/status", json={"status": "approved"})
    assert r.status_code == 200, r.text


def test_archiving_event_removes_tasks_from_active_lists(login, org):
    cid, team = _team_with_members(login, org, ["sw_emp", "mech_emp"])
    _assign_team_task(login, team)
    before = login("sw_emp").get("/api/tasks", params={"view": "assigned"}).json()
    assert any(t["event_team_id"] == team["id"] for t in before)

    r = login("cto").patch(f"/api/events/{cid}", json={"status": "archived"})
    assert r.status_code == 200, r.text

    after = login("sw_emp").get("/api/tasks", params={"view": "assigned"}).json()
    assert not any(t["event_team_id"] == team["id"] for t in after)


def test_archived_event_is_listed_publicly(login, org):
    cid, _team = _team_with_members(login, org, ["sw_emp"])
    login("cto").patch(f"/api/events/{cid}", json={"status": "archived"})
    # a plain Member (bottom of the ladder) can still browse the archive
    r = login("comp_member").get("/api/archive/events")
    assert r.status_code == 200
    assert any(e["id"] == cid for e in r.json())
    # active events are not in the archive
    active_cid = _comp(login, "cto", name="StillOn").json()["id"]
    assert not any(e["id"] == active_cid for e in login("comp_member").get("/api/archive/events").json())


def test_archive_detail_shows_only_own_outcomes(login, org):
    cid, team = _team_with_members(login, org, ["sw_emp", "mech_emp"])
    tasks = _assign_team_task(login, team)
    by_assignee = {t["assignee"]["id"]: t for t in tasks}
    _approve(login, by_assignee[org["sw_emp"].id], "sw_emp")  # accomplished
    # mech_emp leaves theirs untouched -> incomplete
    login("cto").patch(f"/api/events/{cid}", json={"status": "archived"})

    detail = login("sw_emp").get(f"/api/archive/events/{cid}").json()
    assert [t["task"]["assignee"]["id"] for t in detail["tasks"]] == [org["sw_emp"].id]
    assert detail["tasks"][0]["outcome"] == "accomplished"
    assert detail["tasks"][0]["team_name"] == team["name"]
    assert team["name"] in detail["teams"]

    mech = login("mech_emp").get(f"/api/archive/events/{cid}").json()
    assert [t["task"]["assignee"]["id"] for t in mech["tasks"]] == [org["mech_emp"].id]
    assert mech["tasks"][0]["outcome"] == "incomplete"


def test_archive_detail_empty_for_non_participant(login, org):
    cid, _team = _team_with_members(login, org, ["sw_emp"])
    login("cto").patch(f"/api/events/{cid}", json={"status": "archived"})
    detail = login("fin_emp").get(f"/api/archive/events/{cid}").json()
    assert detail["tasks"] == []
    assert detail["teams"] == []
