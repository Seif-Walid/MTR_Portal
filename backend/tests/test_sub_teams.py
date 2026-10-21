"""Optional sub-teams: an event team nested inside another team of its category."""

from tests.test_event_teams import _appoint_lead, _category, _comp, _team


def _tree_by_title(login):
    def walk(nodes):
        out = {}
        for n in nodes:
            out[n["title"]] = n
            out.update(walk(n["children"]))
        return out
    return walk(login("admin").get("/api/org/tree").json())


def _sub(login, cat_id, parent_id, who="cto", name="Sub"):
    return login(who).post(
        f"/api/events/categories/{cat_id}/teams", json={"name": name, "parent_team_id": parent_id}
    )


def _setup(login):
    cid = _comp(login, "cto").json()["id"]
    cat = _category(login, cid).json()
    parent = _team(login, cat["id"], name="Line1").json()
    return cid, cat, parent


def test_teams_stay_top_level_by_default(login, org):
    _, _, parent = _setup(login)
    assert parent["parent_team_id"] is None


def test_create_sub_team_and_tree_order(login, org):
    cid, cat, parent = _setup(login)
    other = _team(login, cat["id"], name="Line2").json()
    r = _sub(login, cat["id"], parent["id"], name="Software")
    assert r.status_code == 201, r.text
    sub = r.json()
    assert sub["parent_team_id"] == parent["id"]

    teams = login("cto").get(f"/api/events/{cid}").json()["categories"][0]["teams"]
    # depth-first: the sub-team follows its parent, before the next top-level team
    assert [t["id"] for t in teams] == [parent["id"], sub["id"], other["id"]]


def test_sub_team_must_share_the_category(login, org):
    cid, _, parent = _setup(login)
    other_cat = _category(login, cid, name="Junior").json()
    r = _sub(login, other_cat["id"], parent["id"])
    assert r.status_code == 400


def test_parent_team_lead_manages_sub_teams_but_not_the_reverse(login, org):
    _, cat, parent = _setup(login)
    _appoint_lead(login, parent, org["student"].id)

    # the parent team's lead may carve a sub-team (no event-level power needed)
    r = _sub(login, cat["id"], parent["id"], who="student", name="Software")
    assert r.status_code == 201, r.text
    sub = r.json()
    assert sub["can_edit"] is True and sub["can_manage_members"] is True
    # ...and run it
    assert login("student").post(
        f"/api/events/teams/{sub['id']}/members", json={"user_id": org["comp_member"].id}
    ).status_code == 201
    assert login("student").patch(
        f"/api/events/teams/{sub['id']}", json={"name": "SW"}
    ).status_code == 200
    # but not a top-level team, nor re-nest teams (that's the event managers' call)
    assert login("student").patch(
        f"/api/events/teams/{parent['id']}", json={"name": "X"}
    ).status_code == 403
    assert login("student").patch(
        f"/api/events/teams/{sub['id']}", json={"clear_parent": True}
    ).status_code == 403

    # a sub-team's lead does not manage the parent
    _appoint_lead(login, sub, org["comp_member"].id)
    assert login("comp_member").post(
        f"/api/events/teams/{parent['id']}/members", json={"user_id": org["fin_emp"].id}
    ).status_code == 403


def test_sub_team_people_count_on_the_parent(login, org):
    _, cat, parent = _setup(login)
    sub = _sub(login, cat["id"], parent["id"]).json()
    login("cto").post(f"/api/events/teams/{sub['id']}/members", json={"user_id": org["student"].id})

    # whole-team task on the parent reaches the sub-team member too
    r = login("cto").post("/api/tasks", json={"title": "all hands", "event_team_id": parent["id"]})
    assert r.status_code == 201, r.text
    assert org["student"].id in {t["assignee"]["id"] for t in r.json()}

    # and the member sees both teams in My Teams, the sub-team by its path
    names = {b["name"] for b in login("student").get("/api/team/mine").json() if b["kind"] == "event"}
    assert names == {"Line1", "Line1 › Sub"}


def test_cannot_delete_a_team_with_sub_teams(login, org):
    _, cat, parent = _setup(login)
    sub = _sub(login, cat["id"], parent["id"]).json()
    assert login("cto").delete(f"/api/events/teams/{parent['id']}").status_code == 400
    assert login("cto").delete(f"/api/events/teams/{sub['id']}").status_code == 204
    assert login("cto").delete(f"/api/events/teams/{parent['id']}").status_code == 204


def test_move_rejects_cycles_and_renests(login, org):
    _, cat, parent = _setup(login)
    sub = _sub(login, cat["id"], parent["id"]).json()
    deeper = _sub(login, cat["id"], sub["id"], name="Deeper").json()

    for target in (parent["id"], sub["id"], deeper["id"]):
        r = login("cto").patch(f"/api/events/teams/{parent['id']}", json={"parent_team_id": target})
        assert r.status_code == 400, target

    r = login("cto").patch(f"/api/events/teams/{deeper['id']}", json={"clear_parent": True})
    assert r.status_code == 200 and r.json()["parent_team_id"] is None
    r = login("cto").patch(f"/api/events/teams/{deeper['id']}", json={"parent_team_id": parent["id"]})
    assert r.status_code == 200 and r.json()["parent_team_id"] == parent["id"]


def test_sub_team_seats_nest_under_the_parent_teams_seats(login, org):
    _, cat, parent = _setup(login)
    sub = _sub(login, cat["id"], parent["id"], name="Software").json()
    tree = _tree_by_title(login)
    assert tree["Software Lead"]["parent_id"] == tree["Line1 Lead"]["id"]

    # moved to the top level, it chains under the event seat like any team
    login("cto").patch(f"/api/events/teams/{sub['id']}", json={"clear_parent": True})
    tree = _tree_by_title(login)
    assert tree["Software Lead"]["parent_id"] == tree["Line1 Lead"]["parent_id"]


def test_hall_of_fame_skips_empty_container_teams(login, org, db_session):
    from app.domains.events.hall_of_fame import event_groups
    from app.domains.events.models import Event

    cid, cat, parent = _setup(login)
    sub = _sub(login, cat["id"], parent["id"], name="Software").json()
    login("cto").post(f"/api/events/teams/{sub['id']}/members", json={"user_id": org["student"].id})
    event = db_session.get(Event, cid)
    db_session.expire_all()
    assert [g["label"] for g in event_groups(event)] == ["Line1 › Software"]
    # the archive (with ids) still lists the container, to edit its placement
    assert [g["label"] for g in event_groups(event, with_ids=True)] == ["Line1", "Line1 › Software"]
    # a container with its own placement is shown publicly
    login("cto").patch(f"/api/events/teams/{parent['id']}", json={"award": "8th place"})
    db_session.expire_all()
    assert [g["label"] for g in event_groups(event)] == ["Line1", "Line1 › Software"]
