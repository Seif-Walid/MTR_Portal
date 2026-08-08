"""The management view (/api/users) doubles as the member directory: it
surfaces each account's roster profile alongside its access/seat data, and
stays gated by users.manage."""

from datetime import date

from app.domains.users.models import MemberProfile


def _add_profile(db, user_id: int, **fields) -> None:
    db.add(MemberProfile(user_id=user_id, **fields))
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

    # a user without a roster row still appears, with profile == None
    assert by_id[org["admin"].id]["profile"] is None


def test_users_list_requires_users_manage(login, org):
    # a non-manager (Lead) can't reach the management/directory view
    assert login("cto").get("/api/users").status_code == 403
