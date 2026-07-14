"""Status workflow: To Do -> In Progress -> Submitted -> Approved / Revision.
Review is restricted to the assigner or anyone above the assigner."""

from tests.conftest import make_task


def set_status(login, who, task_id, status):
    return login(who).patch(f"/api/tasks/{task_id}/status", json={"status": status})


def test_assignee_drives_progress(login, org):
    t = make_task(login, "mech_lead", org, "mech_emp")
    assert set_status(login, "mech_emp", t["id"], "in_progress").status_code == 200
    assert set_status(login, "mech_emp", t["id"], "submitted").status_code == 200


def test_only_assignee_can_progress(login, org):
    t = make_task(login, "cto", org, "sw_emp")
    # even the assigner can't move the work forward on the assignee's behalf
    assert set_status(login, "cto", t["id"], "in_progress").status_code == 403


def test_invalid_transitions_rejected(login, org):
    t = make_task(login, "cto", org, "sw_emp")
    assert set_status(login, "sw_emp", t["id"], "approved").status_code == 400  # todo -> approved
    assert set_status(login, "sw_emp", t["id"], "submitted").status_code == 400  # skip in_progress


def test_review_rights_assigner_or_above(login, org):
    t = make_task(login, "mech_lead", org, "mech_emp")
    set_status(login, "mech_emp", t["id"], "in_progress")
    set_status(login, "mech_emp", t["id"], "submitted")

    # the assignee cannot approve their own work
    assert set_status(login, "mech_emp", t["id"], "approved").status_code == 403

    # assigner can request revision; assignee resumes, resubmits
    assert set_status(login, "mech_lead", t["id"], "revision_requested").status_code == 200
    notif = login("mech_emp").get("/api/notifications").json()
    assert any(n["type"] == "task_status_changed" and n["task_id"] == t["id"] for n in notif)

    assert set_status(login, "mech_emp", t["id"], "in_progress").status_code == 200
    assert set_status(login, "mech_emp", t["id"], "submitted").status_code == 200

    # CTO and CEO are above the assigner -> may approve; CFO is not
    assert set_status(login, "cfo", t["id"], "approved").status_code == 404  # can't even see it
    assert set_status(login, "ceo", t["id"], "approved").status_code == 200

    # assigner is notified about the approval
    notif = login("mech_lead").get("/api/notifications").json()
    assert any(n["type"] == "task_status_changed" and n["task_id"] == t["id"] for n in notif)


def test_assignment_notification_sent(login, org):
    t = make_task(login, "team_lead", org, "student", "read paper")
    notif = login("student").get("/api/notifications").json()
    assert any(n["type"] == "task_assigned" and n["task_id"] == t["id"] for n in notif)
    # unread count reflects it, mark-read clears it
    assert login("student").get("/api/notifications/unread-count").json()["count"] >= 1
    login("student").post("/api/notifications/mark-read", json={})
    assert login("student").get("/api/notifications/unread-count").json()["count"] == 0
