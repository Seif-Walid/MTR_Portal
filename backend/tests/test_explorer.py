"""The data explorer: schema + relations, per-domain visibility, record view
with links both ways (joins shown as their far side, member <-> account twin),
search and lists."""

from app.domains.events.models import Event, EventCategory, EventParticipation, EventTeam, EventTeamMember
from app.domains.users.models import MemberProfile


def _seed(db, org):
    ev = Event(name="MRC 2025", code="MRC25")
    db.add(ev)
    db.flush()
    cat = EventCategory(event_id=ev.id, name="Line")
    db.add(cat)
    db.flush()
    team = EventTeam(category_id=cat.id, name="Line 1")
    db.add(team)
    db.flush()
    m = MemberProfile(user_id=org["student"].id, full_name="Student Roster Name", mtr_id="MTR-021")
    db.add(m)
    db.flush()
    db.add_all([
        EventTeamMember(team_id=team.id, user_id=org["student"].id, role="Software"),
        EventParticipation(event_id=ev.id, member_id=m.id, role="Software", team="Line 1"),
    ])
    db.commit()
    return ev, team, m


def _grant(db, org, who, *privs):
    import json
    from app.domains.access.models import AccessLevel
    level = db.get(AccessLevel, org[who].access_level_id)
    level.privileges = json.dumps(sorted(set(json.loads(level.privileges)) | set(privs)))
    db.commit()


def test_dashboard_is_board_and_above(login, org, db_session):
    # Exec has every view privilege but not dashboard.view -> locked out
    assert login("ceo").get("/api/explore/schema").status_code == 403
    assert login("ceo").get("/api/explore/events").status_code == 403
    _grant(db_session, org, "ceo", "dashboard.view")
    assert login("ceo").get("/api/explore/schema").status_code == 200


def test_schema_respects_privileges(login, org, db_session):
    admin = login("admin").get("/api/explore/schema").json()
    tables = {e["table"] for e in admin["entities"]}
    assert {"users", "member_profiles", "events", "budget_lines", "tasks"} <= tables
    assert any(l["source"] == "event_teams" and l["target"] == "event_categories" for l in admin["links"])
    # with the dashboard, someone still only sees the domains they're allowed:
    # events but not the roster, the books or the work log
    _grant(db_session, org, "comp_member", "dashboard.view")
    member = {e["table"] for e in login("comp_member").get("/api/explore/schema").json()["entities"]}
    assert "events" in member and not member & {"member_profiles", "budget_lines", "tasks"}
    assert login("comp_member").get("/api/explore/budget_lines").status_code == 404


def test_record_links_both_ways(login, org, db_session):
    ev, team, m = _seed(db_session, org)
    admin = login("admin")
    rec = admin.get(f"/api/explore/events/{ev.id}").json()
    groups = {g["table"]: g for g in rec["incoming"]}
    assert groups["event_categories"]["rows"][0]["title"] == "Line"
    assert groups["event_participations"]["total"] == 1

    # a team shows its roster as the people on it (the join's far side)
    t = admin.get(f"/api/explore/event_teams/{team.id}").json()
    people = next(g for g in t["incoming"] if g["table"] == "users")
    assert people["rows"][0]["id"] == org["student"].id and people["rows"][0]["fields"]["role"] == "Software"
    assert any(o["table"] == "event_categories" for o in t["outgoing"])

    # a member also shows what their portal account is part of
    mem = admin.get(f"/api/explore/member_profiles/{m.id}").json()
    via = [g for g in mem["incoming"] if g["via"] == "Portal account"]
    assert any(g["table"] == "event_teams" for g in via)
    assert not any(f["name"] == "hashed_password" for f in admin.get(f"/api/explore/users/{org['student'].id}").json()["fields"])


def test_search_and_list(login, org, db_session):
    _seed(db_session, org)
    admin = login("admin")
    hits = admin.get("/api/explore/search?q=roster name").json()
    assert hits and hits[0]["table"] == "member_profiles"
    page = admin.get("/api/explore/events?q=mrc").json()
    assert page["total"] == 1 and page["rows"][0]["title"] == "MRC 2025"
    assert admin.get("/api/explore/events/999999").status_code == 404


def test_record_says_what_can_be_edited(login, org, db_session):
    ev, team, m = _seed(db_session, org)
    admin = login("admin")
    schema = {e["table"]: e for e in admin.get("/api/explore/schema").json()["entities"]}
    assert schema["member_profiles"]["edit"] == "member_profiles"
    assert schema["audit_log"]["edit"] is None

    rec = admin.get(f"/api/explore/member_profiles/{m.id}").json()
    assert rec["edit"] == "member_profiles"
    parts = next(g for g in rec["incoming"] if g["table"] == "event_participations" and not g["via"])
    assert parts["edit"] == "event_participations" and parts["fk"] == "member_id"
    # lists it has nothing in yet are offered as "add"
    assert any(a["edit"] == "dues_payments" and a["fk"] == "member_id" for a in rec["addable"])

    # Board with dashboard.view but no edit privileges sees no edit handles
    _grant(db_session, org, "comp_member", "dashboard.view")
    rec = login("comp_member").get(f"/api/explore/events/{ev.id}").json()
    assert rec["edit"] is None and rec["addable"] == []
