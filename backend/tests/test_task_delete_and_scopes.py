"""Deleting tasks (tasks.delete privilege) and the per-event task scopes."""

from tests.conftest import make_task
from tests.test_task_features import _team_with_members


def test_delete_needs_the_privilege_even_for_the_assigner(login, org):
    t = make_task(login, "mech_lead", org, "mech_emp")
    # Lead level lacks tasks.delete: being the assigner is not enough
    r = login("mech_lead").delete(f"/api/tasks/{t['id']}")
    assert r.status_code == 403
    assert login("mech_lead").get(f"/api/tasks/{t['id']}").status_code == 200


def test_holder_of_privilege_deletes_task_and_trail_survives(login, org):
    t = make_task(login, "mech_lead", org, "mech_emp")
    login("mech_emp").post(f"/api/tasks/{t['id']}/comments", json={"body": "hi"})
    r = login("admin").delete(f"/api/tasks/{t['id']}")
    assert r.status_code == 204, r.text
    assert login("admin").get(f"/api/tasks/{t['id']}").status_code == 404
    # the assignee's notification about it is gone too
    notifs = login("mech_emp").get("/api/notifications").json()
    assert not any(n["task_id"] == t["id"] for n in notifs)
    audit = login("admin").get("/api/audit", params={"domain": "tasks"}).json()
    rows = audit["items"] if isinstance(audit, dict) else audit
    assert any(a["action"] == "deleted" and a["entity_id"] == t["id"] for a in rows)


def test_cannot_delete_a_task_you_cannot_see(login, org):
    t = make_task(login, "cto", org, "sw_emp")
    assert login("cfo").delete(f"/api/tasks/{t['id']}").status_code == 404


def test_scopes_list_event_with_teams_and_counts(login, org):
    event_id, team = _team_with_members(login, org, ["sw_emp"])
    r = login("cto").post("/api/tasks", json={
        "title": "Team work", "assignee_ids": [org["sw_emp"].id], "event_team_id": team["id"],
    })
    assert r.status_code == 201, r.text
    make_task(login, "cto", org, "sw_emp")  # an unscoped task

    scopes = login("cto").get("/api/tasks/scopes", params={"view": "created"}).json()
    ev = next(s for s in scopes if s["event_id"] == event_id)
    assert ev["task_count"] == 1
    assert [t["task_count"] for t in ev["teams"] if t["team_id"] == team["id"]] == [1]

    by_event = login("cto").get("/api/tasks", params={"view": "created", "event_id": event_id}).json()
    assert [t["title"] for t in by_event] == ["Team work"]
    by_team = login("cto").get("/api/tasks", params={"view": "created", "team_id": team["id"]}).json()
    assert len(by_team) == 1
    everything = login("cto").get("/api/tasks", params={"view": "created"}).json()
    assert len(everything) == 2


def test_assignable_narrows_to_a_team(login, org):
    _, team = _team_with_members(login, org, ["sw_emp"])
    everyone = {u["id"] for u in login("cto").get("/api/users/assignable").json()}
    on_team = {u["id"] for u in login("cto").get(
        "/api/users/assignable", params={"team_id": team["id"]}).json()}
    assert org["sw_emp"].id in on_team
    assert on_team < everyone
