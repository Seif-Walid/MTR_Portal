"""Phase 7: blocked state, comments, history, and multi-assignee (team) tasks."""

from tests.conftest import make_task


def test_assignee_can_block_and_unblock(login, org):
    t = make_task(login, "mech_lead", org, "mech_emp")
    r = login("mech_emp").patch(
        f"/api/tasks/{t['id']}/blocked", json={"is_blocked": True, "reason": "waiting on parts"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["is_blocked"] is True
    assert body["blocked_reason"] == "waiting on parts"

    # assigner is notified
    notif = login("mech_lead").get("/api/notifications").json()
    assert any(n["type"] == "task_status_changed" and n["task_id"] == t["id"] for n in notif)

    r = login("mech_emp").patch(f"/api/tasks/{t['id']}/blocked", json={"is_blocked": False})
    assert r.status_code == 200
    assert r.json()["is_blocked"] is False
    assert r.json()["blocked_reason"] == ""


def test_assigner_can_also_toggle_blocked(login, org):
    t = make_task(login, "mech_lead", org, "mech_emp")
    r = login("mech_lead").patch(
        f"/api/tasks/{t['id']}/blocked", json={"is_blocked": True, "reason": "budget hold"}
    )
    assert r.status_code == 200


def test_unrelated_user_cannot_toggle_blocked(login, org):
    t = make_task(login, "cto", org, "sw_emp")
    # cfo can't even see this task
    r = login("cfo").patch(f"/api/tasks/{t['id']}/blocked", json={"is_blocked": True})
    assert r.status_code == 404


def test_comments_round_trip_and_visible_to_both_sides(login, org):
    t = make_task(login, "mech_lead", org, "mech_emp")
    r = login("mech_emp").post(f"/api/tasks/{t['id']}/comments", json={"body": "starting now"})
    assert r.status_code == 201
    assert r.json()["comments"][-1]["body"] == "starting now"
    assert r.json()["comments"][-1]["author"]["id"] == org["mech_emp"].id

    r = login("mech_lead").post(f"/api/tasks/{t['id']}/comments", json={"body": "sounds good"})
    assert r.status_code == 201
    bodies = [c["body"] for c in r.json()["comments"]]
    assert bodies == ["starting now", "sounds good"]

    # commenter is notified on the other side
    notif = login("mech_emp").get("/api/notifications").json()
    assert any(n["type"] == "task_comment" and n["task_id"] == t["id"] for n in notif)


def test_a_subtree_manager_who_can_view_may_also_comment(login, org):
    # CTO can see everything under them, including a task assigned by mech_lead
    t = make_task(login, "mech_lead", org, "mech_emp")
    r = login("cto").post(f"/api/tasks/{t['id']}/comments", json={"body": "checking in"})
    assert r.status_code == 201


def test_unrelated_user_cannot_comment(login, org):
    t = make_task(login, "cto", org, "sw_emp")
    r = login("cfo").post(f"/api/tasks/{t['id']}/comments", json={"body": "nope"})
    assert r.status_code == 404


def test_history_records_status_changes_edits_and_blocked(login, org):
    t = make_task(login, "mech_lead", org, "mech_emp")
    login("mech_emp").patch(f"/api/tasks/{t['id']}/status", json={"status": "in_progress"})
    login("mech_lead").patch(f"/api/tasks/{t['id']}", json={"priority": "urgent"})
    login("mech_emp").patch(
        f"/api/tasks/{t['id']}/blocked", json={"is_blocked": True, "reason": "stuck"}
    )

    r = login("mech_lead").get(f"/api/tasks/{t['id']}/history")
    assert r.status_code == 200
    actions = [e["action"] for e in r.json()]
    # newest first
    assert actions == ["blocked", "edited", "status_changed", "created"]


def test_history_visible_to_participants_not_outsiders(login, org):
    t = make_task(login, "cto", org, "sw_emp")
    assert login("sw_emp").get(f"/api/tasks/{t['id']}/history").status_code == 200
    assert login("cto").get(f"/api/tasks/{t['id']}/history").status_code == 200
    assert login("cfo").get(f"/api/tasks/{t['id']}/history").status_code == 404


def test_multi_assignee_creates_a_batch(login, org):
    r = login("cto").post(
        "/api/tasks",
        json={
            "title": "team task",
            "assignee_ids": [org["sw_emp"].id, org["mech_emp"].id],
        },
    )
    assert r.status_code == 201
    tasks = r.json()
    assert len(tasks) == 2
    assert tasks[0]["batch_id"] is not None
    assert tasks[0]["batch_id"] == tasks[1]["batch_id"]
    assert {t["assignee"]["id"] for t in tasks} == {org["sw_emp"].id, org["mech_emp"].id}

    # each assignee got their own notification
    for who in ("sw_emp", "mech_emp"):
        notif = login(who).get("/api/notifications").json()
        assert any(n["type"] == "task_assigned" for n in notif)


def test_single_assignee_has_no_batch_id(login, org):
    t = make_task(login, "cto", org, "sw_emp")
    assert t["batch_id"] is None


def test_batch_assignment_is_atomic_on_bad_assignee(login, org):
    # sw_emp is in the CTO's subtree, ceo is not assignable by the CTO
    r = login("cto").post(
        "/api/tasks",
        json={"title": "bad batch", "assignee_ids": [org["sw_emp"].id, org["ceo"].id]},
    )
    assert r.status_code == 403
    seen = login("cto").get("/api/tasks", params={"view": "all"}).json()
    assert not any(t["title"] == "bad batch" for t in seen)


def test_batch_view_limited_to_assigner(login, org):
    r = login("cto").post(
        "/api/tasks",
        json={"title": "batch view", "assignee_ids": [org["sw_emp"].id, org["mech_emp"].id]},
    )
    batch_id = r.json()[0]["batch_id"]

    r = login("cto").get(f"/api/tasks/batch/{batch_id}")
    assert r.status_code == 200
    assert len(r.json()) == 2

    r = login("sw_emp").get(f"/api/tasks/batch/{batch_id}")
    assert r.status_code == 403

    r = login("admin").get(f"/api/tasks/batch/{batch_id}")
    assert r.status_code == 200


def test_batch_not_found(login, org):
    assert login("cto").get("/api/tasks/batch/does-not-exist").status_code == 404
