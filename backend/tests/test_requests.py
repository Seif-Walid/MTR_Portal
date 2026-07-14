"""Rule 2: requests flow up or across; accept spawns a trackable task."""


def send(login, org, requester, recipient, title="please"):
    return login(requester).post(
        "/api/requests", json={"recipient_id": org[recipient].id, "title": title}
    )


def test_request_up_and_across(login, org):
    assert send(login, org, "sw_emp", "cto").status_code == 201  # up
    assert send(login, org, "pm", "cto").status_code == 201  # across branches
    assert send(login, org, "student", "media_mgr").status_code == 201  # non-staff can ask


def test_request_into_own_subtree_rejected(login, org):
    # you can task them directly, so no request
    assert send(login, org, "cto", "mech_emp").status_code == 400
    assert send(login, org, "ceo", "cfo").status_code == 400


def test_request_to_non_staff_rejected(login, org):
    assert send(login, org, "pm", "student").status_code == 400  # student in own subtree anyway
    assert send(login, org, "cfo", "comp_member").status_code == 400  # non-staff
    assert send(login, org, "sw_emp", "sw_emp").status_code == 400  # self


def test_accept_spawns_task_and_notifies_requester(login, org):
    req = send(login, org, "pm", "cto", "need CI server").json()

    # recipient sees it in their received box + gets a notification
    received = login("cto").get("/api/requests", params={"box": "received"}).json()
    assert any(r["id"] == req["id"] for r in received)
    notif = login("cto").get("/api/notifications").json()
    assert any(n["request_id"] == req["id"] and n["type"] == "request_received" for n in notif)

    # only the recipient can accept
    assert login("ceo").post(f"/api/requests/{req['id']}/accept", json={}).status_code == 404
    r = login("cto").post(f"/api/requests/{req['id']}/accept", json={})
    assert r.status_code == 200
    accepted = r.json()
    assert accepted["status"] == "accepted"
    task_id = accepted["created_task_id"]
    assert task_id is not None

    # requester is notified and can track the spawned task even though the
    # recipient is outside their subtree
    notif = login("pm").get("/api/notifications").json()
    assert any(n["type"] == "request_accepted" and n["task_id"] == task_id for n in notif)
    r = login("pm").get(f"/api/tasks/{task_id}")
    assert r.status_code == 200
    assert r.json()["assignee"]["id"] == org["cto"].id

    # and sees live status on the request listing
    sent = login("pm").get("/api/requests", params={"box": "sent"}).json()
    assert sent[0]["created_task_status"] == "todo"

    # can't resolve twice
    assert login("cto").post(f"/api/requests/{req['id']}/accept", json={}).status_code == 400


def test_accept_with_delegation_into_subtree(login, org):
    req = send(login, org, "cfo", "cto", "fix finance dashboard").json()
    # delegating outside the recipient's subtree is forbidden
    r = login("cto").post(
        f"/api/requests/{req['id']}/accept", json={"assignee_id": org["fin_emp"].id}
    )
    assert r.status_code == 403
    # delegating into the subtree works and assigns the task there
    r = login("cto").post(
        f"/api/requests/{req['id']}/accept", json={"assignee_id": org["sw_emp"].id}
    )
    assert r.status_code == 200
    task_id = r.json()["created_task_id"]
    task = login("cfo").get(f"/api/tasks/{task_id}").json()  # requester tracks it
    assert task["assignee"]["id"] == org["sw_emp"].id
    assert task["assigner"]["id"] == org["cto"].id
    # the delegate is notified
    notif = login("sw_emp").get("/api/notifications").json()
    assert any(n["type"] == "task_assigned" and n["task_id"] == task_id for n in notif)


def test_decline_requires_reason_and_notifies(login, org):
    req = send(login, org, "media_mgr", "cfo", "budget for campaign").json()
    assert login("cfo").post(f"/api/requests/{req['id']}/decline", json={"reason": ""}).status_code == 422
    r = login("cfo").post(
        f"/api/requests/{req['id']}/decline", json={"reason": "No budget this quarter"}
    )
    assert r.status_code == 200
    assert r.json()["status"] == "declined"
    assert r.json()["decline_reason"] == "No budget this quarter"

    notif = login("media_mgr").get("/api/notifications").json()
    assert any(n["type"] == "request_declined" for n in notif)


def test_requests_private_to_participants(login, org):
    req = send(login, org, "sw_emp", "media_mgr").json()
    assert login("cfo").get(f"/api/requests/{req['id']}").status_code == 404
    assert login("sw_emp").get(f"/api/requests/{req['id']}").status_code == 200
    assert login("media_mgr").get(f"/api/requests/{req['id']}").status_code == 200
