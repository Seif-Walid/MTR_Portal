"""Checkout requests: submit -> approve/reject -> issue -> return, and the
guard that issuing/returning is the only path that moves stock."""


def _item(login, org, who="cto", quantity=10, **over):
    # designated to the team lead so non-staff requesters (student/comp_member,
    # both under team_lead in the fixture org) can see and request it
    body = {"name": "Arduino", "quantity": quantity, "team_lead_id": org["team_lead"].id}
    body.update(over)
    return login(who).post("/api/inventory", json=body)


def _loc(login, who="cto", name="Lab A"):
    return login(who).post("/api/inventory/locations", json={"name": name})


def _stock_in(login, iid, lid, qty, who="cto"):
    return login(who).post(f"/api/inventory/{iid}/movements", json={"quantity": qty, "to_location_id": lid})


def test_full_lifecycle_submit_approve_issue_return(login, org):
    iid = _item(login, org).json()["id"]
    lid = _loc(login).json()["id"]
    _stock_in(login, iid, lid, 10)

    r = login("student").post("/api/inventory/requests", json={"item_id": iid, "quantity": 3, "reason": "R&D"})
    assert r.status_code == 201, r.text
    req = r.json()
    assert req["status"] == "submitted"

    r = login("cto").post(f"/api/inventory/requests/{req['id']}/approve")
    assert r.status_code == 200 and r.json()["status"] == "approved"

    r = login("cto").post(f"/api/inventory/requests/{req['id']}/issue", json={"from_location_id": lid})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "issued"

    w = login("cto").get(f"/api/inventory/{iid}/whereabouts").json()
    holder_qty = {p["holder"]["id"]: p["quantity"] for p in w["by_holder"]}
    assert holder_qty[org["student"].id] == 3
    loc_qty = {p["location"]["id"]: p["quantity"] for p in w["by_location"]}
    assert loc_qty[lid] == 7

    # requester returns it themselves
    r = login("student").post(f"/api/inventory/requests/{req['id']}/return", json={"to_location_id": lid})
    assert r.status_code == 200 and r.json()["status"] == "returned"
    w = login("cto").get(f"/api/inventory/{iid}/whereabouts").json()
    assert w["by_holder"] == []
    assert {p["location"]["id"]: p["quantity"] for p in w["by_location"]}[lid] == 10


def test_reject_records_reason_and_blocks_issue(login, org):
    iid = _item(login, org).json()["id"]
    req = login("student").post("/api/inventory/requests", json={"item_id": iid, "quantity": 1}).json()
    r = login("cto").post(f"/api/inventory/requests/{req['id']}/reject", json={"reason": "not needed"})
    assert r.status_code == 200
    assert r.json()["status"] == "rejected" and r.json()["decision_reason"] == "not needed"
    # can't approve/issue a rejected request
    assert login("cto").post(f"/api/inventory/requests/{req['id']}/approve").status_code == 400


def test_cannot_issue_without_approval_or_skip_states(login, org):
    iid = _item(login, org).json()["id"]
    lid = _loc(login).json()["id"]
    req = login("student").post("/api/inventory/requests", json={"item_id": iid, "quantity": 1}).json()
    # straight to issue without approval
    assert login("cto").post(f"/api/inventory/requests/{req['id']}/issue", json={"from_location_id": lid}).status_code == 400


def test_only_manager_approves_only_requester_or_manager_returns(login, org):
    iid = _item(login, org).json()["id"]
    lid = _loc(login).json()["id"]
    _stock_in(login, iid, lid, 5)
    req = login("student").post("/api/inventory/requests", json={"item_id": iid, "quantity": 2}).json()
    assert login("student").post(f"/api/inventory/requests/{req['id']}/approve").status_code == 403
    login("cto").post(f"/api/inventory/requests/{req['id']}/approve")
    login("cto").post(f"/api/inventory/requests/{req['id']}/issue", json={"from_location_id": lid})
    # a random other non-staff member can't even see someone else's request
    # (404, not 403 — visibility is requester-or-manager, so existence isn't leaked)
    assert login("comp_member").post(
        f"/api/inventory/requests/{req['id']}/return", json={"to_location_id": lid}
    ).status_code == 404


def test_views_mine_and_to_review(login, org):
    iid = _item(login, org).json()["id"]
    req = login("student").post("/api/inventory/requests", json={"item_id": iid, "quantity": 1}).json()

    mine = login("student").get("/api/inventory/requests?view=mine").json()
    assert any(r["id"] == req["id"] for r in mine)

    to_review = login("cto").get("/api/inventory/requests?view=to_review").json()
    assert any(r["id"] == req["id"] for r in to_review)
    # a non-manager can't use to_review
    assert login("student").get("/api/inventory/requests?view=to_review").status_code == 403


def test_low_stock_endpoint(login, org):
    iid = _item(login, org, quantity=3, low_stock_threshold=5).json()["id"]
    items = login("cto").get("/api/inventory/low-stock").json()
    assert any(i["id"] == iid for i in items)
    # inventory.view is enough for the readout now; a no-view tier gets 403
    assert any(i["id"] == iid for i in login("student").get("/api/inventory/low-stock").json())
    assert login("comp_member").get("/api/inventory/low-stock").status_code == 403


def test_overdue_flag(login, org):
    iid = _item(login, org).json()["id"]
    lid = _loc(login).json()["id"]
    _stock_in(login, iid, lid, 5)
    req = login("student").post(
        "/api/inventory/requests",
        json={"item_id": iid, "quantity": 1, "return_by": "2000-01-01"},
    ).json()
    login("cto").post(f"/api/inventory/requests/{req['id']}/approve")
    r = login("cto").post(f"/api/inventory/requests/{req['id']}/issue", json={"from_location_id": lid})
    assert r.json()["is_overdue"] is True
