"""Allocation capacity math, guards, and the who-holds-what breakdown."""


def _item(login, who="cto", quantity=100, **over):
    body = {"name": "Arduino", "quantity": quantity}
    body.update(over)
    r = login(who).post("/api/inventory", json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _alloc(login, item_id, quantity, purpose="training", who="cto", **over):
    body = {"quantity": quantity, "purpose": purpose}
    body.update(over)
    return login(who).post(f"/api/inventory/{item_id}/allocations", json=body)


def test_allocations_compute_in_use_and_free(login, org):
    item_id = _item(login, quantity=100)
    _alloc(login, item_id, 50, "training")
    _alloc(login, item_id, 30, "competition", label="RoboCup")
    r = _alloc(login, item_id, 10, "research")
    assert r.status_code == 201
    item = r.json()
    assert item["in_use"] == 90
    assert item["free"] == 10
    assert item["by_purpose"] == {"training": 50, "competition": 30, "research": 10}


def test_cannot_over_allocate(login, org):
    item_id = _item(login, quantity=10)
    _alloc(login, item_id, 8, "training")
    r = _alloc(login, item_id, 5, "competition")
    assert r.status_code == 400
    assert "free" in r.json()["detail"].lower()


def test_cannot_shrink_below_in_use(login, org):
    item_id = _item(login, quantity=100)
    _alloc(login, item_id, 95, "training")
    r = login("cto").patch(f"/api/inventory/{item_id}", json={"quantity": 90})
    assert r.status_code == 400
    # but shrinking to exactly in-use is fine
    assert login("cto").patch(f"/api/inventory/{item_id}", json={"quantity": 95}).json()["free"] == 0


def test_edit_allocation_excludes_itself_from_capacity(login, org):
    item_id = _item(login, quantity=20)
    alloc_id = _alloc(login, item_id, 20, "training").json()["allocations"][0]["id"]
    # growing back to 20 must not double-count the allocation being edited
    r = login("cto").patch(f"/api/inventory/allocations/{alloc_id}", json={"quantity": 20})
    assert r.status_code == 200
    assert r.json()["in_use"] == 20


def test_holder_breakdown_reports_who_has_what(login, org):
    item_id = _item(login, quantity=100)
    student_id = org["student"].id
    _alloc(login, item_id, 2, "research", label="R&D", holder_id=student_id)
    r = _alloc(login, item_id, 1, "competition", label="RoboCup", holder_id=student_id)
    held = [a for a in r.json()["allocations"] if a["holder"]]
    by_purpose = {a["purpose"]: a["quantity"] for a in held if a["holder"]["id"] == student_id}
    assert by_purpose == {"research": 2, "competition": 1}


def test_delete_allocation_frees_capacity(login, org):
    item_id = _item(login, quantity=10)
    alloc_id = _alloc(login, item_id, 10, "training").json()["allocations"][0]["id"]
    assert login("cto").get(f"/api/inventory/{item_id}").json()["free"] == 0
    assert login("cto").delete(f"/api/inventory/allocations/{alloc_id}").status_code == 204
    assert login("cto").get(f"/api/inventory/{item_id}").json()["free"] == 10


def test_non_staff_cannot_manage_allocations(login, org):
    item_id = _item(login, team_lead_id=None)
    r = _alloc(login, item_id, 1, who="student")
    # non-staff can't even see the general-storage item → 404
    assert r.status_code == 404
