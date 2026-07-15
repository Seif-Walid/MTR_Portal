"""Competition CRUD, archiving, and linkage from inventory allocations."""


def _comp(login, who="cto", name="RoboCup 2026", **over):
    body = {"name": name, "season": "2026"}
    body.update(over)
    return login(who).post("/api/competitions", json=body)


def test_staff_creates_competition_non_staff_cannot(login, org):
    r = _comp(login, "cto")
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "active"
    assert _comp(login, "student", name="X").status_code == 403


def test_duplicate_name_conflicts(login, org):
    _comp(login, "cto", name="VEX")
    assert _comp(login, "cto", name="VEX").status_code == 409


def test_list_hides_archived_by_default(login, org):
    keep = _comp(login, "cto", name="Active Cup").json()
    gone = _comp(login, "cto", name="Old Cup").json()
    login("cto").patch(f"/api/competitions/{gone['id']}", json={"status": "archived"})

    active_names = {c["name"] for c in login("cto").get("/api/competitions").json()}
    assert "Active Cup" in active_names and "Old Cup" not in active_names

    all_names = {c["name"] for c in login("cto").get("/api/competitions?include_archived=true").json()}
    assert {"Active Cup", "Old Cup"} <= all_names
    assert keep["id"]  # sanity


def test_allocation_links_to_competition(login, org):
    comp_id = _comp(login, "cto", name="RoboCup").json()["id"]
    item_id = login("cto").post("/api/inventory", json={"name": "Arduino", "quantity": 20}).json()["id"]
    r = login("cto").post(
        f"/api/inventory/{item_id}/allocations",
        json={"quantity": 5, "purpose": "competition", "competition_id": comp_id},
    )
    assert r.status_code == 201, r.text
    alloc = r.json()["allocations"][0]
    assert alloc["competition"]["name"] == "RoboCup"
    assert alloc["display_label"] == "RoboCup"  # competition name wins over free-text label


def test_cannot_delete_competition_in_use_but_can_archive(login, org):
    comp_id = _comp(login, "cto", name="RoboCup").json()["id"]
    item_id = login("cto").post("/api/inventory", json={"name": "Arduino", "quantity": 20}).json()["id"]
    login("cto").post(
        f"/api/inventory/{item_id}/allocations",
        json={"quantity": 5, "purpose": "competition", "competition_id": comp_id},
    )
    assert login("cto").delete(f"/api/competitions/{comp_id}").status_code == 400
    # archiving is allowed
    assert login("cto").patch(f"/api/competitions/{comp_id}", json={"status": "archived"}).status_code == 200


def test_delete_unused_competition(login, org):
    comp_id = _comp(login, "cto", name="Unused").json()["id"]
    assert login("cto").delete(f"/api/competitions/{comp_id}").status_code == 204
