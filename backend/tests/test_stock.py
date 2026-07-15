"""Stock ledger: locations, movements, derived whereabouts, guards, low-stock."""


def _item(login, who="cto", **over):
    body = {"name": "Arduino", "quantity": 10}
    body.update(over)
    return login(who).post("/api/inventory", json=body)


def _loc(login, who="cto", name="Lab A"):
    return login(who).post("/api/inventory/locations", json={"name": name, "kind": "shelf"})


def test_location_management_is_staff_only(login, org):
    assert _loc(login, "cto").status_code == 201
    assert _loc(login, "student").status_code == 403


def test_stock_in_then_move_derives_whereabouts(login, org):
    iid = _item(login).json()["id"]
    lid = _loc(login).json()["id"]
    # stock-in 10 into the location (from nowhere)
    r = login("cto").post(f"/api/inventory/{iid}/movements", json={"quantity": 10, "to_location_id": lid, "reason": "in"})
    assert r.status_code == 201, r.text
    w = r.json()
    assert w["owned"] == 10 and w["tracked"] == 10
    assert w["by_location"][0]["quantity"] == 10

    # move 3 to a holder
    r = login("cto").post(f"/api/inventory/{iid}/movements",
                          json={"quantity": 3, "from_location_id": lid, "to_holder_id": org["student"].id})
    w = r.json()
    by_loc = {p["location"]["id"]: p["quantity"] for p in w["by_location"]}
    assert by_loc[lid] == 7
    assert w["by_holder"][0]["holder"]["id"] == org["student"].id and w["by_holder"][0]["quantity"] == 3
    assert w["tracked"] == 10  # conserved


def test_cannot_move_more_than_on_hand(login, org):
    iid = _item(login).json()["id"]
    lid = _loc(login).json()["id"]
    login("cto").post(f"/api/inventory/{iid}/movements", json={"quantity": 5, "to_location_id": lid})
    r = login("cto").post(f"/api/inventory/{iid}/movements",
                          json={"quantity": 8, "from_location_id": lid, "to_holder_id": org["student"].id})
    assert r.status_code == 400
    assert "on hand" in r.json()["detail"].lower()


def test_ledger_and_low_stock_flag(login, org):
    iid = _item(login, "cto", quantity=5, low_stock_threshold=5).json()["id"]
    lid = _loc(login).json()["id"]
    login("cto").post(f"/api/inventory/{iid}/movements", json={"quantity": 5, "to_location_id": lid})
    ledger = login("cto").get(f"/api/inventory/{iid}/movements").json()
    assert len(ledger) == 1 and ledger[0]["quantity"] == 5
    w = login("cto").get(f"/api/inventory/{iid}/whereabouts").json()
    assert w["low_stock"] is True  # owned 5 <= threshold 5


def test_stock_out_reduces_tracked(login, org):
    iid = _item(login).json()["id"]
    lid = _loc(login).json()["id"]
    login("cto").post(f"/api/inventory/{iid}/movements", json={"quantity": 10, "to_location_id": lid})
    # consume 4 (to nowhere)
    r = login("cto").post(f"/api/inventory/{iid}/movements", json={"quantity": 4, "from_location_id": lid, "reason": "consumed"})
    assert r.json()["tracked"] == 6
