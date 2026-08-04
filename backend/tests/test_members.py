"""Member directory: profiles surface through /users/members, and the
endpoint is gated by people.view."""

from datetime import date

from app.domains.users.models import MemberProfile, User


def _add_profile(db, user_id: int, **fields) -> None:
    db.add(MemberProfile(user_id=user_id, **fields))
    db.commit()


def test_members_lists_active_users_with_profile(login, org, db_session):
    _add_profile(
        db_session, org["student"].id,
        mtr_id="MTR-021", university="ANU", major="CCE",
        graduating_year=2030, phone="01207084513",
        birthday=date(2007, 1, 10), location="Alexandria",
    )
    rows = login("cto").get("/api/users/members").json()
    by_id = {r["id"]: r for r in rows}

    student = by_id[org["student"].id]
    assert student["profile"]["mtr_id"] == "MTR-021"
    assert student["profile"]["graduating_year"] == 2030
    assert student["profile"]["birthday"] == "2007-01-10"
    assert student["level"] == "Requester"  # effective level name

    # a user without a roster row still appears, with profile == None
    assert by_id[org["cto"].id]["profile"] is None


def test_members_excludes_inactive(login, org, db_session):
    org["student"].is_active = False
    db_session.commit()
    ids = {r["id"] for r in login("cto").get("/api/users/members").json()}
    assert org["student"].id not in ids


def test_members_requires_people_view(login, org, db_session):
    guest = User(
        email="guest@t.local", full_name="Guest",
        hashed_password=org["student"].hashed_password, access_level_id=None,
    )
    db_session.add(guest)
    db_session.commit()
    # log in as the guest (no access level -> no people.view) -> forbidden
    from tests.conftest import As
    as_guest = As(login("cto").client, "guest@t.local")
    resp = as_guest.get("/api/users/members")
    assert resp.status_code == 403, resp.text
