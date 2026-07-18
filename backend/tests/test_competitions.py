"""Competition CRUD, high-staff gate, archiving, and role-position authority."""

from tests.conftest import ensure_position, setup_role_templates


def _comp(login, who="cto", name="RoboCup 2026", **over):
    admin = login("admin")
    setup_role_templates(admin, pm=True)
    body = {"name": name}
    if not admin.get("/api/org/roles/root").json()["root_position_id"]:
        body["role_root_position_id"] = ensure_position(admin)
    body.update(over)
    return login(who).post("/api/competitions", json=body)


def _pm_position_id(comp_json: dict) -> int:
    return comp_json["roles"][0]["position_id"]


def test_high_staff_creates_and_is_auto_pm(login, org):
    r = _comp(login, "cto")
    assert r.status_code == 201, r.text
    data = r.json()
    assert any(u["id"] == org["cto"].id for u in data["roles"][0]["occupants"])  # creator auto-seated
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


def test_role_occupant_appointment_grants_scoped_management(login, org):
    comp = _comp(login, "cto").json()
    cid = comp["id"]
    pos_id = _pm_position_id(comp)
    # the creator (already an occupant via auto_assign_creator) appoints a
    # plain employee (not high staff) as a co-occupant of the PM role
    r = login("cto").put(
        f"/api/org/roles/positions/{pos_id}/occupants",
        json={"user_ids": [org["cto"].id, org["sw_emp"].id]},
    )
    assert r.status_code == 200, r.text
    # as an occupant, the employee can now manage THIS competition's structure
    assert login("sw_emp").post(f"/api/competitions/{cid}/categories", json={"name": "Senior"}).status_code == 201
    # but someone who manages nothing cannot touch the roles panel at all
    assert login("student").put(
        f"/api/org/roles/positions/{pos_id}/occupants", json={"user_ids": [org["student"].id]}
    ).status_code == 403
    assert login("student").post(f"/api/competitions/{cid}/categories", json={"name": "X"}).status_code == 403


def test_role_scope_does_not_leak_across_competitions(login, org):
    a = _comp(login, "cto", name="Comp A").json()
    b = _comp(login, "cto", name="Comp B").json()
    login("cto").put(
        f"/api/org/roles/positions/{_pm_position_id(a)}/occupants",
        json={"user_ids": [org["cto"].id, org["sw_emp"].id]},
    )
    # occupant of A's role can manage A, but not B
    assert login("sw_emp").post(f"/api/competitions/{a['id']}/categories", json={"name": "S"}).status_code == 201
    assert login("sw_emp").post(f"/api/competitions/{b['id']}/categories", json={"name": "S"}).status_code == 403
