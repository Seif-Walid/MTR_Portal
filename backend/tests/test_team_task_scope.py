"""Rule: tasking needs a structural org connection, not a higher access level.

A team lead reaches their own team's people (the team's seats sit under their
seat in the org chart) and nobody else's — the classic case being two sibling
teams, "Sumo 1" and "Sumo 2", where Sumo 1's lead outranks a Sumo 2 member on
the access ladder and still may not task them. The `tasks.assign_any` privilege
is the admin-editable way out.
"""

from tests.conftest import ensure_position, seat_role, setup_role_templates


def _event(login, who="cto", name="Robotics"):
    admin = login("admin")
    setup_role_templates(admin, pm=True, team_lead=True, member=True)
    body = {"name": name}
    if not admin.get("/api/org/roles/root").json()["root_position_id"]:
        body["role_root_position_id"] = ensure_position(admin)
    r = login(who).post("/api/events", json=body)
    assert r.status_code == 201, r.text
    me = login(who).get("/api/auth/me").json()
    seat_role(admin, r.json(), [me["id"]])
    return r.json()["id"]


def _team(login, category_id, name, lead_id, member_ids):
    """A team with its lead seated and its members added."""
    r = login("cto").post(f"/api/events/categories/{category_id}/teams", json={"name": name})
    assert r.status_code == 201, r.text
    team = r.json()
    seat_role(login("admin"), team, [lead_id])
    for uid in member_ids:
        m = login("cto").post(f"/api/events/teams/{team['id']}/members", json={"user_id": uid})
        assert m.status_code in (200, 201), m.text
    return team


def _sumo(login, org):
    """Two sibling teams under one event:

    Sumo 1: lead mech_lead, member fin_emp   (fin_emp reports to the cfo)
    Sumo 2: lead elec_lead, member comp_member
    """
    event_id = _event(login)
    cat = login("cto").post(f"/api/events/{event_id}/categories", json={"name": "Senior"}).json()
    one = _team(login, cat["id"], "Sumo 1", org["mech_lead"].id, [org["fin_emp"].id])
    two = _team(login, cat["id"], "Sumo 2", org["elec_lead"].id, [org["comp_member"].id])
    return one, two


def _assign(login, org, assigner, assignee):
    return login(assigner).post(
        "/api/tasks", json={"title": "x", "assignee_ids": [org[assignee].id]}
    )


def test_lead_can_task_own_team_member_outside_their_reporting_line(login, org):
    _sumo(login, org)
    # fin_emp reports to the cfo, not to mech_lead — the team seat is the
    # only connection, and it is enough
    assert _assign(login, org, "mech_lead", "fin_emp").status_code == 201


def test_lead_cannot_task_a_sibling_teams_member(login, org):
    _sumo(login, org)
    # mech_lead's level (Lead) outranks comp_member's (Member) — irrelevant
    assert _assign(login, org, "mech_lead", "comp_member").status_code == 403
    assert _assign(login, org, "elec_lead", "fin_emp").status_code == 403


def test_peers_on_a_team_cannot_task_each_other(login, org):
    _sumo(login, org)
    # member seats are siblings, never above one another
    assert _assign(login, org, "fin_emp", "comp_member").status_code == 403


def test_event_pm_reaches_every_team_below(login, org):
    _sumo(login, org)
    # the cto holds the event's PM seat, above both team seats
    assert _assign(login, org, "cto", "fin_emp").status_code == 201
    assert _assign(login, org, "cto", "comp_member").status_code == 201


def test_assignable_list_is_the_team_scope(login, org):
    _sumo(login, org)
    ids = {u["id"] for u in login("mech_lead").get("/api/users/assignable").json()}
    # self + manager subtree (mech_emp) + own team (fin_emp), no Sumo 2
    assert ids == {org["mech_lead"].id, org["mech_emp"].id, org["fin_emp"].id}


def test_assign_any_privilege_lifts_the_structural_limit(login, org):
    _sumo(login, org)
    assert _assign(login, org, "mech_lead", "comp_member").status_code == 403

    admin = login("admin")
    lead = next(lvl for lvl in admin.get("/api/access/levels").json() if lvl["name"] == "Lead")
    r = admin.patch(
        f"/api/access/levels/{lead['id']}",
        json={"privileges": sorted(set(lead["privileges"]) | {"tasks.assign_any"})},
    )
    assert r.status_code == 200, r.text

    assert _assign(login, org, "mech_lead", "comp_member").status_code == 201
    ids = {u["id"] for u in login("mech_lead").get("/api/users/assignable").json()}
    assert org["ceo"].id in ids  # everyone active, upward included
