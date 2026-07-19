"""Inventory CRUD, hierarchy-scoped visibility, and sync gating."""


def _item(login, who, org, **over):
    body = {"name": "Arduino", "quantity": 10}
    body.update(over)
    return login(who).post("/api/inventory", json=body)


def test_staff_can_create_item(login, org):
    r = _item(login, "cto", org)
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["quantity"] == 10
    assert data["in_use"] == 0
    assert data["free"] == 10


def test_non_staff_cannot_create(login, org):
    r = _item(login, "student", org)
    assert r.status_code == 403


def test_without_inventory_view_the_storage_is_invisible(login, org):
    # visibility is the inventory.view privilege now — all storage or none;
    # the old "designated to my team lead" carve-out is gone with the ladder
    _item(login, "cto", org, name="Team kit", team_lead_id=org["team_lead"].id)
    _item(login, "cto", org, name="General", team_lead_id=None)

    staff_names = {i["name"] for i in login("cto").get("/api/inventory").json()}
    assert {"Team kit", "General"} <= staff_names

    assert login("comp_member").get("/api/inventory").json() == []


def test_without_inventory_view_items_404(login, org):
    item_id = _item(login, "cto", org, team_lead_id=None).json()["id"]
    # 404 (not 403) so existence isn't leaked to levels with no view at all
    assert login("comp_member").get(f"/api/inventory/{item_id}").status_code == 404


def test_edit_and_delete_need_the_edit_privilege(login, org):
    item_id = _item(login, "cto", org, team_lead_id=org["team_lead"].id).json()["id"]

    # a requester tier sees the item but lacks inventory.edit
    assert login("student").patch(f"/api/inventory/{item_id}", json={"name": "x"}).status_code == 403
    assert login("student").delete(f"/api/inventory/{item_id}").status_code == 403

    assert login("cto").patch(f"/api/inventory/{item_id}", json={"location": "Lab B"}).json()["location"] == "Lab B"
    assert login("cto").delete(f"/api/inventory/{item_id}").status_code == 204
    assert login("cto").get(f"/api/inventory/{item_id}").status_code == 404


def test_holders_picker_needs_people_view(login, org):
    # people.view gates the picker — the member tier has it
    holders = login("student").get("/api/inventory/holders").json()
    assert any(h["email"] == org["student"].email for h in holders)


def test_sync_gated_when_unconfigured(login, org):
    status = login("cto").get("/api/inventory/sheets/status").json()
    assert status["configured"] is False and status["can_sync"] is True
    assert status["credentials"] is False  # no service-account key in tests
    assert login("cto").post("/api/inventory/sync").status_code == 503
    # non-staff can't sync at all
    assert login("student").post("/api/inventory/sync").status_code == 403
