"""Join applications: the website's public intake (validation, honeypot, rate
limit, resubmission) and the authenticated review side (gating, status,
roster matching, add-to-roster)."""

from datetime import datetime, timedelta, timezone

from app.domains.applications.models import Application
from app.domains.notifications.models import Notification
from app.domains.users.models import MemberProfile

FORM = {
    "name": "Mariam Ahmed Hassan",
    "email": "Mariam@Gmail.com",
    "phone": "010 1234 5678",
    "school": "Alexandria University",
    "year": "University — 1st year",
    "subteam": "",
    "why": "I have built a line follower and want to build an ROV next.",
}


def _apply(client, **over):
    return client.post("/api/public/applications", json={**FORM, **over})


def test_public_submit_stores_and_notifies_reviewers(client, org, db_session):
    r = _apply(client)
    assert r.status_code == 201, r.text
    assert r.json() == {"received": True}  # nothing stored is echoed back
    a = db_session.query(Application).one()
    assert a.email == "mariam@gmail.com"
    assert a.subteam is None  # "not sure yet"
    assert a.status == "new"
    assert a.client_hash and "testclient" not in a.client_hash
    # only accounts holding members.edit (the test ladder's Admin) hear about it
    notified = {n.user_id for n in db_session.query(Notification).filter_by(type="application_received")}
    assert notified == {org["admin"].id}


def test_public_submit_validates(client, org):
    assert _apply(client, email="not-an-email").status_code == 422
    assert _apply(client, phone="123").status_code == 422
    assert _apply(client, why="too short").status_code == 422
    assert _apply(client, name=" ").status_code == 422


def test_honeypot_is_silently_dropped(client, org, db_session):
    r = _apply(client, website="http://spam.example")
    assert r.status_code == 201
    assert db_session.query(Application).count() == 0


def test_resubmitting_within_a_day_updates_instead_of_duplicating(client, org, db_session):
    _apply(client)
    _apply(client, email="mariam@gmail.com", subteam="Software")
    rows = db_session.query(Application).all()
    assert len(rows) == 1
    assert rows[0].subteam == "software"


def test_rate_limited_per_connection(client, org):
    for i in range(5):
        assert _apply(client, email=f"a{i}@x.test").status_code == 201
    r = _apply(client, email="a5@x.test")
    assert r.status_code == 429
    # a different connection is unaffected
    r = client.post("/api/public/applications", json={**FORM, "email": "b@x.test"},
                    headers={"X-Forwarded-For": "203.0.113.9"})
    assert r.status_code == 201


def test_old_applications_do_not_count_towards_the_limit(client, org, db_session):
    for i in range(5):
        _apply(client, email=f"a{i}@x.test")
    for a in db_session.query(Application):
        a.created_at = datetime.now(timezone.utc) - timedelta(hours=2)
    db_session.commit()
    assert _apply(client, email="late@x.test").status_code == 201


def test_review_is_gated(client, org, login):
    _apply(client)
    assert client.get("/api/applications").status_code == 401
    assert login("sw_emp").get("/api/applications").status_code == 403
    rows = login("admin").get("/api/applications").json()
    assert [r["full_name"] for r in rows] == ["Mariam Ahmed Hassan"]
    assert rows[0]["motivation"].startswith("I have built")


def test_status_and_notes(client, org, login):
    _apply(client)
    admin = login("admin")
    app_id = admin.get("/api/applications").json()[0]["id"]
    assert login("sw_emp").patch(f"/api/applications/{app_id}", json={"status": "contacted"}).status_code == 403
    r = admin.patch(f"/api/applications/{app_id}", json={"status": "contacted", "notes": " Called, session Sat "})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "contacted"
    assert body["notes"] == "Called, session Sat"
    assert body["reviewed_by"] == org["admin"].full_name
    assert admin.patch(f"/api/applications/{app_id}", json={"status": "bogus"}).status_code == 422


def test_add_to_roster_creates_member(client, org, login, db_session):
    db_session.add(MemberProfile(mtr_id="MTR-0007", full_name="Someone Else"))
    db_session.commit()
    _apply(client)
    admin = login("admin")
    app_id = admin.get("/api/applications").json()[0]["id"]
    r = admin.post(f"/api/applications/{app_id}/add-to-roster")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "accepted"
    m = db_session.get(MemberProfile, body["member_id"])
    assert m.full_name == "Mariam Ahmed Hassan"
    assert m.email == "mariam@gmail.com"
    assert m.university == "Alexandria University"
    assert m.mtr_id and m.mtr_id != "MTR-0007"
    assert admin.post(f"/api/applications/{app_id}/add-to-roster").status_code == 409


def test_add_to_roster_links_existing_member(client, org, login, db_session):
    existing = MemberProfile(mtr_id="MTR-0042", full_name="Mariam A.", phone="+20 10 1234 5678")
    db_session.add(existing)
    db_session.commit()
    _apply(client)
    admin = login("admin")
    row = admin.get("/api/applications").json()[0]
    assert row["roster_matches"] == [
        {"id": existing.id, "mtr_id": "MTR-0042", "name": "Mariam A.", "matched_on": ["phone"]}
    ]
    body = admin.post(f"/api/applications/{row['id']}/add-to-roster").json()
    assert body["member_id"] == existing.id
    assert body["member_mtr_id"] == "MTR-0042"
    assert db_session.query(MemberProfile).count() == 1
