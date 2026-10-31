"""The member roster (/api/members): members without a sign-in yet, MTR IDs,
duplicate detection, participations, claiming a roster account, and gating.
A member *is* an account — there is one row and one id per person."""

from datetime import datetime, timezone

from app.domains.events.models import Event, EventParticipation
from tests.conftest import make_member


def _grant(db, org, who, *privs):
    import json
    from app.domains.access.models import AccessLevel
    level = db.get(AccessLevel, org[who].access_level_id)
    level.privileges = json.dumps(sorted(set(json.loads(level.privileges)) | set(privs)))
    db.commit()


def test_roster_is_gated(login, org, db_session):
    assert login("ceo").get("/api/members").status_code == 403
    _grant(db_session, org, "ceo", "members.view")
    assert login("ceo").get("/api/members").status_code == 200
    assert login("ceo").post("/api/members", json={"full_name": "X"}).status_code == 403


def test_create_member_creates_unclaimed_account(login, org, db_session):
    make_member(db_session, "Old", mtr_id="MTR-041")
    db_session.commit()
    admin = login("admin")
    assert admin.get("/api/members/next-id").json() == {"mtr_id": "MTR-042"}
    r = admin.post("/api/members", json={"full_name": "New Kid", "phone": "0120 000 1111"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["mtr_id"] == "MTR-042" and body["claimed"] is False and body["data_confidence"] == "manual"
    # the member is a person everywhere: they show up in the people pickers
    assert any(u["id"] == body["id"] for u in admin.get("/api/users/directory").json())
    # MTR IDs and emails stay unique
    assert admin.post("/api/members", json={"full_name": "Dup", "mtr_id": "MTR-042"}).status_code == 409
    assert admin.post("/api/members", json={"full_name": "Dup", "email": org["student"].email}).status_code == 409


def test_duplicate_check(login, org, db_session):
    make_member(db_session, "Sara Ali", phone="+20 120 555 1234", email="sara@gmail.com")
    db_session.commit()
    hits = login("admin").post("/api/members/check-duplicate", json={
        "name": "sara  ali", "phone": "01205551234", "email": "x@y.com",
    }).json()
    assert len(hits) == 1 and set(hits[0]["matched_on"]) == {"name", "phone"}


def test_participations_on_member(login, org, db_session):
    m = make_member(db_session, "Racer", mtr_id="MTR-050")
    ev = Event(name="MRC 2025", code="MRC25")
    db_session.add(ev)
    db_session.flush()
    db_session.add(EventParticipation(event_id=ev.id, member_id=m.id, role="Software", team="Line 1", rating="95.5"))
    db_session.commit()
    admin = login("admin")
    row = next(r for r in admin.get("/api/members").json() if r["id"] == m.id)
    assert row["events"] == ["MRC25"]
    detail = admin.get(f"/api/members/{m.id}").json()
    assert detail["participations"][0]["team"] == "Line 1"
    stats = admin.get("/api/members/stats").json()
    assert stats["totals"]["participations"] == 1 and stats["events"][0]["participants"] == 1


def test_signup_claims_roster_account(client, db_session, org):
    m = make_member(db_session, "Roster Person", mtr_id="MTR-060", email="person@gmail.com",
                    joined_at=datetime(2025, 1, 1, tzinfo=timezone.utc))
    db_session.commit()
    r = client.post("/api/auth/register", json={
        "email": "Person@gmail.com", "full_name": "Person", "password": "longenough1",
    })
    assert r.status_code == 201, r.text
    assert r.json()["id"] == m.id and r.json()["profile"]["mtr_id"] == "MTR-060"
    db_session.refresh(m)
    assert m.claimed
    # once claimed, the email is taken like any other
    client.cookies.clear()
    assert client.post("/api/auth/register", json={
        "email": "person@gmail.com", "full_name": "Thief", "password": "longenough1",
    }).status_code == 409


def test_unclaimed_member_cannot_password_login(client, db_session, org):
    make_member(db_session, "Quiet", email="quiet@gmail.com")
    db_session.commit()
    r = client.post("/api/auth/login", json={"email": "quiet@gmail.com", "password": "!"})
    assert r.status_code == 401


def test_only_unclaimed_unreferenced_members_can_be_deleted(login, org, db_session):
    lone = make_member(db_session, "Lone")
    db_session.commit()
    admin = login("admin")
    # someone who has signed in is retired by deactivating, never deleted
    assert admin.delete(f"/api/members/{org['student'].id}").status_code == 400
    assert admin.delete(f"/api/members/{lone.id}").status_code == 204


def test_event_card_carries_record_and_participations(login, org, db_session):
    m = make_member(db_session, "Pilot", mtr_id="MTR-070")
    ev = Event(name="MATE ROV 2026", code="ROV26", level="International", result="8th", budget_total=174950)
    db_session.add(ev)
    db_session.flush()
    db_session.add(EventParticipation(event_id=ev.id, member_id=m.id, role="Pilot"))
    db_session.commit()
    admin = login("admin")
    card = admin.get(f"/api/events/{ev.id}").json()
    assert card["code"] == "ROV26" and card["record"]["result"] == "8th" and card["participation_count"] == 1
    assert "notes" not in card["record"]  # unset fields are left out
    parts = admin.get(f"/api/events/{ev.id}/participations").json()
    assert parts[0]["name"] == "Pilot" and parts[0]["mtr_id"] == "MTR-070"
    assert login("comp_member").get(f"/api/events/{ev.id}/participations").status_code == 403
