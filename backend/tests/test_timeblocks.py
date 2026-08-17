"""Team time blocks: event-team blocks expand onto the calendar as spans or
weekly recurrences, honour me/general scope and the manage-team gate."""

from datetime import date

from app.domains.timeblocks.models import TimeBlock
from app.domains.timeblocks.service import expand_block
from tests.conftest import ensure_position, seat_role, setup_role_templates


def _team_with_member(login, org):
    """A MATE ROV event with cto seated as PM (a manager) and student as a team
    member. Returns the team dict."""
    admin = login("admin")
    setup_role_templates(admin, pm=True, member=True)
    root = ensure_position(admin)
    comp = login("cto").post("/api/events", json={
        "name": "MATE ROV", "start_date": "2026-09-01", "end_date": "2027-04-24",
        "role_root_position_id": root,
    }).json()
    seat_role(admin, comp, [org["cto"].id])
    cat = login("cto").post(f"/api/events/{comp['id']}/categories", json={"name": "Senior"}).json()
    team = login("cto").post(f"/api/events/categories/{cat['id']}/teams", json={"name": "Alpha"}).json()
    login("cto").post(f"/api/events/teams/{team['id']}/members", json={"user_id": org["student"].id})
    return team


def _cal(login, who, scope, sources, **params):
    r = login(who).get("/api/calendar", params={"scope": scope, "sources": sources, **params})
    assert r.status_code == 200, r.text
    return r.json()


def test_expand_block_span_vs_weekly():
    span = TimeBlock(team_type="event", start_date=date(2026, 8, 3),
                     end_date=date(2026, 8, 9), weekday_mask=0)
    assert expand_block(span, None, None) == [(date(2026, 8, 3), date(2026, 8, 9))]

    # Mondays only (bit 0) across two weeks → two single-day marks
    mondays = TimeBlock(team_type="event", start_date=date(2026, 8, 1),
                        end_date=date(2026, 8, 14), weekday_mask=1)
    out = expand_block(mondays, None, None)
    assert out == [(date(2026, 8, 3), None), (date(2026, 8, 10), None)]

    # window clamps the span
    assert expand_block(span, date(2026, 8, 5), date(2026, 8, 6)) == [
        (date(2026, 8, 5), date(2026, 8, 6))
    ]


def test_event_block_span_on_calendar(login, org):
    team = _team_with_member(login, org)
    r = login("cto").post("/api/timeblocks", json={
        "team_type": "event", "event_team_id": team["id"], "title": "Build week",
        "start_date": "2026-09-07", "end_date": "2026-09-13", "weekday_mask": 0,
    })
    assert r.status_code == 201, r.text

    items = [i for i in _cal(login, "cfo", "general", "teams") if i["title"] == "Build week"]
    assert len(items) == 1
    assert items[0]["source"] == "team" and items[0]["kind"] == "event"
    assert items[0]["start"] == "2026-09-07" and items[0]["end"] == "2026-09-13"


def test_event_block_weekly_expands_and_scopes(login, org):
    team = _team_with_member(login, org)
    # every Monday in September 2026 (bit 0)
    r = login("cto").post("/api/timeblocks", json={
        "team_type": "event", "event_team_id": team["id"], "title": "Mondays",
        "start_date": "2026-09-01", "end_date": "2026-09-30", "weekday_mask": 1,
    })
    assert r.status_code == 201, r.text

    marks = [i for i in _cal(login, "cfo", "general", "teams",
                             start="2026-09-01", end="2026-09-30") if i["title"] == "Mondays"]
    starts = sorted(m["start"] for m in marks)
    assert starts == ["2026-09-07", "2026-09-14", "2026-09-21", "2026-09-28"]
    assert all(m["end"] is None for m in marks)

    # me scope: the team member (student) sees it; an outsider doesn't
    assert any(i["title"] == "Mondays" for i in _cal(login, "student", "me", "teams",
                                                     start="2026-09-01", end="2026-09-30"))
    assert _cal(login, "media_mgr", "me", "teams",
                start="2026-09-01", end="2026-09-30") == []


def test_block_create_requires_manage(login, org):
    team = _team_with_member(login, org)
    # student is only a member — cannot schedule the team's time
    r = login("student").post("/api/timeblocks", json={
        "team_type": "event", "event_team_id": team["id"],
        "start_date": "2026-09-07", "end_date": "2026-09-13", "weekday_mask": 0,
    })
    assert r.status_code == 403, r.text


def test_event_block_cannot_leave_event_span(login, org):
    # event runs 2026-09-01 .. 2027-04-24 (see _team_with_member)
    team = _team_with_member(login, org)
    before = login("cto").post("/api/timeblocks", json={
        "team_type": "event", "event_team_id": team["id"],
        "start_date": "2026-08-20", "end_date": "2026-09-05", "weekday_mask": 0,
    })
    assert before.status_code == 400 and "before the event" in before.json()["detail"]

    after = login("cto").post("/api/timeblocks", json={
        "team_type": "event", "event_team_id": team["id"],
        "start_date": "2027-04-20", "end_date": "2027-05-10", "weekday_mask": 0,
    })
    assert after.status_code == 400 and "past the event" in after.json()["detail"]

    ok = login("cto").post("/api/timeblocks", json={
        "team_type": "event", "event_team_id": team["id"],
        "start_date": "2026-09-07", "end_date": "2026-09-13", "weekday_mask": 0,
    })
    assert ok.status_code == 201, ok.text


def test_delete_block(login, org):
    team = _team_with_member(login, org)
    block = login("cto").post("/api/timeblocks", json={
        "team_type": "event", "event_team_id": team["id"],
        "start_date": "2026-09-07", "end_date": "2026-09-13", "weekday_mask": 0,
    }).json()
    assert login("cto").delete(f"/api/timeblocks/{block['id']}").status_code == 204
    assert _cal(login, "cto", "general", "teams") == []
