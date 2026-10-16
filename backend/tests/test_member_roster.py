"""The member roster (/api/members): roster-only members, MTR IDs, duplicate
detection, participations, linking a sign-up to its roster row, and gating."""

from datetime import datetime, timezone

from app.domains.events.models import Event, EventParticipation
from app.domains.users.models import MemberProfile


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


def test_create_roster_only_member_with_next_id(login, org, db_session):
    db_session.add(MemberProfile(full_name="Old", mtr_id="MTR-041"))
    db_session.commit()
    admin = login("admin")
    assert admin.get("/api/members/next-id").json() == {"mtr_id": "MTR-042"}
    r = admin.post("/api/members", json={"full_name": "New Kid", "phone": "0120 000 1111"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["mtr_id"] == "MTR-042" and body["has_account"] is False and body["data_confidence"] == "manual"
    # MTR IDs stay unique
    assert admin.post("/api/members", json={"full_name": "Dup", "mtr_id": "MTR-042"}).status_code == 409


def test_duplicate_check(login, org, db_session):
    db_session.add(MemberProfile(full_name="Sara Ali", phone="+20 120 555 1234", email="sara@gmail.com"))
    db_session.commit()
    hits = login("admin").post("/api/members/check-duplicate", json={
        "name": "sara  ali", "phone": "01205551234", "email": "x@y.com",
    }).json()
    assert len(hits) == 1 and set(hits[0]["matched_on"]) == {"name", "phone"}


def test_participations_on_member(login, org, db_session):
    m = MemberProfile(full_name="Racer", mtr_id="MTR-050")
    ev = Event(name="MRC 2025", code="MRC25")
    db_session.add_all([m, ev])
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


def test_signup_claims_roster_row(client, db_session, org):
    m = MemberProfile(full_name="Roster Person", mtr_id="MTR-060", email="person@gmail.com",
                      joined_at=datetime(2025, 1, 1, tzinfo=timezone.utc))
    db_session.add(m)
    db_session.commit()
    r = client.post("/api/auth/register", json={
        "email": "Person@gmail.com", "full_name": "Person", "password": "longenough1",
    })
    assert r.status_code == 201, r.text
    assert r.json()["profile"]["mtr_id"] == "MTR-060"
    db_session.refresh(m)
    assert m.user_id is not None


def test_cannot_delete_member_with_account(login, org, db_session):
    m = MemberProfile(user_id=org["student"].id, full_name="Student")
    lone = MemberProfile(full_name="Lone")
    db_session.add_all([m, lone])
    db_session.commit()
    admin = login("admin")
    assert admin.delete(f"/api/members/{m.id}").status_code == 400
    assert admin.delete(f"/api/members/{lone.id}").status_code == 204


def test_event_card_carries_record_and_participations(login, org, db_session):
    m = MemberProfile(full_name="Pilot", mtr_id="MTR-070")
    ev = Event(name="MATE ROV 2026", code="ROV26", level="International", result="8th", budget_total=174950)
    db_session.add_all([m, ev])
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
