"""Positions org tree: permissions, single root, cycles, occupant->manager
derivation (including vacant-seat skip), delete guards, and the audit log."""

from app.domains.users.models import User


def _pos(login, who="ceo", occupant_id=None, **body):
    if occupant_id is not None:
        body["occupant_ids"] = [occupant_id]
    return login(who).post("/api/org/positions", json=body)


def test_only_ceo_and_admin_edit_and_single_root(login, org):
    root = _pos(login, "ceo", title="CEO", occupant_id=org["ceo"].id)
    assert root.status_code == 201, root.text
    rid = root.json()["id"]
    # a second root is rejected
    assert _pos(login, "ceo", title="Root 2").status_code == 400
    # admin may also edit
    assert _pos(login, "admin", title="CTO", parent_id=rid).status_code == 201
    # a high-staff non-CEO (CTO) and a non-staff member cannot
    assert _pos(login, "cto", title="X", parent_id=rid).status_code == 403
    assert _pos(login, "student", title="Y", parent_id=rid).status_code == 403


def test_manager_is_derived_from_positions(login, org, db_session):
    root = _pos(login, "ceo", title="CEO", occupant_id=org["ceo"].id).json()
    cfo = _pos(login, "ceo", title="CFO", parent_id=root["id"], occupant_id=org["cfo"].id).json()
    # sw_emp is seeded under the CTO, but placing them under the CFO must re-derive
    _pos(login, "ceo", title="Finance Member", parent_id=cfo["id"], occupant_id=org["sw_emp"].id)
    db_session.expire_all()
    assert db_session.get(User, org["sw_emp"].id).manager_id == org["cfo"].id


def test_vacant_seat_is_skipped_in_derivation(login, org, db_session):
    root = _pos(login, "ceo", title="CEO", occupant_id=org["ceo"].id).json()
    cto = _pos(login, "ceo", title="CTO", parent_id=root["id"], occupant_id=org["cto"].id).json()
    lead = _pos(login, "ceo", title="Software Lead", parent_id=cto["id"]).json()  # vacant
    _pos(login, "ceo", title="Member", parent_id=lead["id"], occupant_id=org["mech_emp"].id)
    db_session.expire_all()
    # skips the empty Software Lead seat, reports to the CTO
    assert db_session.get(User, org["mech_emp"].id).manager_id == org["cto"].id


def test_reparent_cycle_rejected(login, org):
    a = _pos(login, "ceo", title="A", occupant_id=org["ceo"].id).json()
    b = _pos(login, "ceo", title="B", parent_id=a["id"]).json()
    c = _pos(login, "ceo", title="C", parent_id=b["id"]).json()
    # moving A under its own descendant C is a cycle
    r = login("ceo").patch(f"/api/org/positions/{a['id']}", json={"parent_id": c["id"]})
    assert r.status_code == 400


def test_delete_requires_leaf(login, org):
    a = _pos(login, "ceo", title="A", occupant_id=org["ceo"].id).json()
    b = _pos(login, "ceo", title="B", parent_id=a["id"]).json()
    assert login("ceo").delete(f"/api/org/positions/{a['id']}").status_code == 400  # has a child
    assert login("ceo").delete(f"/api/org/positions/{b['id']}").status_code == 204  # leaf ok


def test_occupant_moves_between_seats(login, org, db_session):
    from app.domains.positions.models import Position

    root = _pos(login, "ceo", title="CEO", occupant_id=org["ceo"].id).json()
    p1 = _pos(login, "ceo", title="Seat 1", parent_id=root["id"], occupant_id=org["cto"].id).json()
    p2 = _pos(login, "ceo", title="Seat 2", parent_id=root["id"]).json()
    # move the CTO into Seat 2 → Seat 1 becomes vacant
    login("ceo").patch(f"/api/org/positions/{p2['id']}", json={"occupant_ids": [org["cto"].id]})
    db_session.expire_all()
    assert db_session.get(Position, p1["id"]).occupants == []
    assert [u.id for u in db_session.get(Position, p2["id"]).occupants] == [org["cto"].id]


def test_position_can_have_multiple_occupants(login, org, db_session):
    from app.domains.positions.models import Position

    r = login("ceo").post("/api/org/positions", json={
        "title": "Co-Leadership", "occupant_ids": [org["ceo"].id, org["cfo"].id],
    })
    assert r.status_code == 201, r.text
    pos_id = r.json()["id"]
    db_session.expire_all()
    occupant_ids = {u.id for u in db_session.get(Position, pos_id).occupants}
    assert occupant_ids == {org["ceo"].id, org["cfo"].id}


def test_audit_log_records_changes(login, org):
    _pos(login, "ceo", title="CEO", occupant_id=org["ceo"].id)
    entries = login("ceo").get("/api/org/audit").json()
    assert entries and entries[0]["action"] == "create"
    assert login("student").get("/api/org/audit").status_code == 403
