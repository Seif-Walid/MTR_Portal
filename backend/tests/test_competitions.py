"""Competition CRUD, high-staff gate, archiving, and PM appointment/scoping."""


def _comp(login, who="cto", name="RoboCup 2026", **over):
    body = {"name": name}
    body.update(over)
    return login(who).post("/api/competitions", json=body)


def test_high_staff_creates_and_is_auto_pm(login, org):
    r = _comp(login, "cto")
    assert r.status_code == 201, r.text
    data = r.json()
    assert any(p["id"] == org["cto"].id for p in data["pms"])  # creator becomes a PM
    assert data["can_manage"] is True
    # a plain employee and a non-staff member cannot create competitions
    assert _comp(login, "sw_emp", name="X").status_code == 403
    assert _comp(login, "student", name="Y").status_code == 403


def test_duplicate_name_conflicts(login, org):
    _comp(login, "cto", name="VEX")
    assert _comp(login, "cto", name="VEX").status_code == 409


def test_archive_hides_by_default(login, org):
    keep = _comp(login, "cto", name="Active Cup").json()
    gone = _comp(login, "cto", name="Old Cup").json()
    login("cto").patch(f"/api/competitions/{gone['id']}", json={"status": "archived"})
    active = {c["name"] for c in login("cto").get("/api/competitions").json()}
    assert "Active Cup" in active and "Old Cup" not in active
    all_names = {c["name"] for c in login("cto").get("/api/competitions?include_archived=true").json()}
    assert {"Active Cup", "Old Cup"} <= all_names
    assert keep["id"]


def test_pm_appointment_grants_scoped_management(login, org):
    cid = _comp(login, "cto").json()["id"]
    # appoint a plain employee (not high staff) as a PM of this competition
    r = login("cto").post(f"/api/competitions/{cid}/pms", json={"user_id": org["sw_emp"].id})
    assert r.status_code == 201, r.text
    # as a PM, the employee can now manage THIS competition's structure
    assert login("sw_emp").post(f"/api/competitions/{cid}/categories", json={"name": "Senior"}).status_code == 201
    # but a random member cannot, and the employee-PM only appoints PMs? no — appointing PMs is high-staff only
    assert login("student").post(f"/api/competitions/{cid}/categories", json={"name": "X"}).status_code == 403
    assert login("sw_emp").post(f"/api/competitions/{cid}/pms", json={"user_id": org["student"].id}).status_code == 403


def test_pm_scope_does_not_leak_across_competitions(login, org):
    a = _comp(login, "cto", name="Comp A").json()["id"]
    b = _comp(login, "cto", name="Comp B").json()["id"]
    login("cto").post(f"/api/competitions/{a}/pms", json={"user_id": org["sw_emp"].id})
    # PM of A can manage A, but not B
    assert login("sw_emp").post(f"/api/competitions/{a}/categories", json={"name": "S"}).status_code == 201
    assert login("sw_emp").post(f"/api/competitions/{b}/categories", json={"name": "S"}).status_code == 403
