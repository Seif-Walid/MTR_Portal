"""The management view (/api/users) doubles as the member directory: it
surfaces each person's roster fields alongside their access/seat data, and
stays gated by users.manage."""

from datetime import date

from app.domains.users.models import User


def _add_profile(db, user_id: int, **fields) -> None:
    user = db.get(User, user_id)
    for k, v in fields.items():
        setattr(user, k, v)
    db.commit()


def test_users_list_carries_roster_profile(login, org, db_session):
    _add_profile(
        db_session, org["student"].id,
        mtr_id="MTR-021", university="ANU", major="CCE",
        graduating_year=2030, phone="01207084513",
        birthday=date(2007, 1, 10), location="Alexandria",
    )
    rows = login("admin").get("/api/users").json()
    by_id = {r["id"]: r for r in rows}

    student = by_id[org["student"].id]
    assert student["profile"]["mtr_id"] == "MTR-021"
    assert student["profile"]["graduating_year"] == 2030
    assert student["profile"]["birthday"] == "2007-01-10"

    # someone with no roster data still appears, with an empty profile
    assert by_id[org["admin"].id]["profile"]["mtr_id"] is None


def test_users_list_requires_users_manage(login, org):
    # a non-manager (Lead) can't reach the management/directory view
    assert login("cto").get("/api/users").status_code == 403


def test_update_sets_roster_fields(login, org, db_session):
    admin = login("admin")
    uid = org["admin"].id

    r = admin.patch(f"/api/users/{uid}", json={
        "profile": {"mtr_id": "MTR-500", "major": "Robotics", "graduating_year": 2029}
    })
    assert r.status_code == 200
    assert r.json()["profile"]["mtr_id"] == "MTR-500"
    assert r.json()["profile"]["graduating_year"] == 2029

    # partial update leaves untouched fields alone; blank clears a field
    r = admin.patch(f"/api/users/{uid}", json={"profile": {"mtr_id": ""}})
    assert r.status_code == 200
    assert r.json()["profile"]["mtr_id"] is None
    assert r.json()["profile"]["major"] == "Robotics"


def test_update_rejects_duplicate_mtr_id(login, org, db_session):
    _add_profile(db_session, org["student"].id, mtr_id="MTR-021")
    r = login("admin").patch(f"/api/users/{org['admin'].id}", json={
        "profile": {"mtr_id": "MTR-021"}
    })
    assert r.status_code == 409


def test_profile_edit_requires_users_manage(login, org):
    r = login("cto").patch(f"/api/users/{org['student'].id}", json={
        "profile": {"mtr_id": "MTR-999"}
    })
    assert r.status_code == 403
