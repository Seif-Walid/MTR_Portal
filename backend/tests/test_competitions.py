"""Competition CRUD, the competitions.create gate, archiving, and
seat-level (manage-where-seated) authority."""

from tests.conftest import ensure_position, seat_role, setup_role_templates


def _comp(login, who="cto", name="RoboCup 2026", **over):
    admin = login("admin")
    setup_role_templates(admin, pm=True)
    body = {"name": name}
    if not admin.get("/api/org/roles/root").json()["root_position_id"]:
        body["role_root_position_id"] = ensure_position(admin)
    body.update(over)
    return login(who).post("/api/competitions", json=body)


def _managed_comp(login, org, who="cto", name="RoboCup 2026", **over) -> dict:
    """Create a competition and seat the creator into its PM role — nothing
    auto-seats anymore, so scoped management is an explicit appointment."""
    r = _comp(login, who, name=name, **over)
    assert r.status_code == 201, r.text
    comp = r.json()
    seat_role(login("admin"), comp, [org[who].id])
    return comp


def _pm_position_id(comp_json: dict) -> int:
    return comp_json["roles"][0]["position_id"]


def test_create_gate_and_vacant_pm_seat(login, org):
    r = _comp(login, "cto")
    assert r.status_code == 201, r.text
    data = r.json()
    # every seat starts vacant — creating a competition grants nothing
    assert data["roles"][0]["occupants"] == []
    assert data["can_manage"] is False
    # a plain staff member and a member-tier user cannot create competitions
    assert _comp(login, "sw_emp", name="X").status_code == 403
    assert _comp(login, "student", name="Y").status_code == 403


def test_duplicate_name_conflicts(login, org):
    _comp(login, "cto", name="VEX")
    assert _comp(login, "cto", name="VEX").status_code == 409


def test_archive_hides_by_default(login, org):
    keep = _managed_comp(login, org, "cto", name="Active Cup")
    gone = _managed_comp(login, org, "cto", name="Old Cup")
    login("cto").patch(f"/api/competitions/{gone['id']}", json={"status": "archived"})
    active = {c["name"] for c in login("cto").get("/api/competitions").json()}
    assert "Active Cup" in active and "Old Cup" not in active
    all_names = {c["name"] for c in login("cto").get("/api/competitions?include_archived=true").json()}
    assert {"Active Cup", "Old Cup"} <= all_names
    assert keep["id"]


def test_role_occupant_appointment_grants_scoped_management(login, org):
    comp = _managed_comp(login, org, "cto")
    cid = comp["id"]
    pos_id = _pm_position_id(comp)
    # a seated PM appoints a plain staff member as a co-occupant
    r = login("cto").put(
        f"/api/org/roles/positions/{pos_id}/occupants",
        json={"user_ids": [org["cto"].id, org["sw_emp"].id]},
    )
    assert r.status_code == 200, r.text
    # as an occupant of a manage_seated-level seat, the employee can now
    # manage THIS competition's structure
    assert login("sw_emp").post(f"/api/competitions/{cid}/categories", json={"name": "Senior"}).status_code == 201
    # but someone who manages nothing cannot touch the roles panel at all
    assert login("student").put(
        f"/api/org/roles/positions/{pos_id}/occupants", json={"user_ids": [org["student"].id]}
    ).status_code == 403
    assert login("student").post(f"/api/competitions/{cid}/categories", json={"name": "X"}).status_code == 403


def test_role_scope_does_not_leak_across_competitions(login, org):
    a = _managed_comp(login, org, "cto", name="Comp A")
    b = _comp(login, "cto", name="Comp B").json()
    login("cto").put(
        f"/api/org/roles/positions/{_pm_position_id(a)}/occupants",
        json={"user_ids": [org["cto"].id, org["sw_emp"].id]},
    )
    # occupant of A's role can manage A, but not B
    assert login("sw_emp").post(f"/api/competitions/{a['id']}/categories", json={"name": "S"}).status_code == 201
    assert login("sw_emp").post(f"/api/competitions/{b['id']}/categories", json={"name": "S"}).status_code == 403
