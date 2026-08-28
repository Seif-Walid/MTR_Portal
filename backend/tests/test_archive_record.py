"""The archive as the source of truth for the public Hall of Fame: an archived
event carries its whole roster, and managers can correct the published record
(official title, awards, per-team placements, per-member roles) without having
to reactivate the event first."""

from sqlalchemy import select

from app.domains.events.models import Event, EventKind, EventStatus
from tests.test_archive import _team_with_members


def _competition_kind_id(db) -> int:
    """The `competition` kind ships as a seeded row — only its archived events
    are published publicly."""
    kind = db.scalars(select(EventKind).where(EventKind.slug == "competition")).first()
    if kind is None:
        kind = EventKind(
            slug="competition",
            name="Competition",
            event_label="Competition",
            category_label="Category",
            team_label="Team",
            member_label="Member",
            sort_order=99,
        )
        db.add(kind)
        db.flush()
    return kind.id


def _archived_with_roster(login, org):
    cid, team = _team_with_members(login, org, ["sw_emp", "mech_emp"])
    login("cto").patch(f"/api/events/{cid}", json={"status": "archived"})
    return cid, team


def test_archive_detail_carries_the_whole_roster(login, org):
    """Every member of every team, not just the viewer's own — the same record
    the website publishes."""
    cid, team = _archived_with_roster(login, org)

    detail = login("comp_member").get(f"/api/archive/events/{cid}").json()
    group = next(g for g in detail["groups"] if g["id"] == team["id"])
    assert group["label"] == team["name"]
    names = {m["name"] for m in group["members"]}
    assert names == {org["sw_emp"].full_name, org["mech_emp"].full_name}


def test_manager_edits_the_published_record_from_the_archive(login, org):
    cid, team = _archived_with_roster(login, org)

    r = login("cto").patch(
        f"/api/archive/events/{cid}",
        json={"full_name": "Mind-Tech Robotics Challenge", "awards": ["🏆 Champions"]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["full_name"] == "Mind-Tech Robotics Challenge"
    assert r.json()["awards"] == ["🏆 Champions"]

    r = login("cto").patch(f"/api/archive/teams/{team['id']}", json={"award": "🥇 1st Place"})
    assert r.status_code == 200, r.text
    assert r.json()["award"] == "🥇 1st Place"

    detail = login("cto").get(f"/api/archive/events/{cid}").json()
    member = next(
        m for g in detail["groups"] for m in g["members"] if m["name"] == org["sw_emp"].full_name
    )
    r = login("cto").patch(f"/api/archive/members/{member['id']}", json={"role": "Electrical"})
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "Electrical"

    # and it all comes back on the record
    detail = login("cto").get(f"/api/archive/events/{cid}").json()
    assert detail["event"]["full_name"] == "Mind-Tech Robotics Challenge"
    assert detail["event"]["awards"] == ["🏆 Champions"]
    group = next(g for g in detail["groups"] if g["id"] == team["id"])
    assert group["award"] == "🥇 1st Place"
    assert next(m for m in group["members"] if m["id"] == member["id"])["role"] == "Electrical"


def test_clearing_the_record_fields(login, org):
    cid, team = _archived_with_roster(login, org)
    login("cto").patch(f"/api/archive/events/{cid}", json={"full_name": "X", "awards": ["Y"]})
    login("cto").patch(f"/api/archive/teams/{team['id']}", json={"award": "Z"})

    r = login("cto").patch(
        f"/api/archive/events/{cid}", json={"clear_full_name": True, "clear_awards": True}
    )
    assert r.json()["full_name"] is None
    assert r.json()["awards"] is None
    r = login("cto").patch(f"/api/archive/teams/{team['id']}", json={"clear_award": True})
    assert r.json()["award"] is None


def test_record_edits_are_manager_gated(login, org):
    cid, team = _archived_with_roster(login, org)
    detail = login("comp_member").get(f"/api/archive/events/{cid}").json()
    member_id = detail["groups"][0]["members"][0]["id"]

    member = login("comp_member")
    assert member.patch(f"/api/archive/events/{cid}", json={"full_name": "nope"}).status_code == 403
    assert member.patch(f"/api/archive/teams/{team['id']}", json={"award": "nope"}).status_code == 403
    assert member.patch(f"/api/archive/members/{member_id}", json={"role": "nope"}).status_code == 403


def test_archive_edits_never_touch_active_events(login, org):
    """The archive endpoints are for history only — a live event keeps its own
    seat-based permission rules and is edited through /api/events."""
    cid, team = _team_with_members(login, org, ["sw_emp"])  # left active
    assert login("cto").patch(f"/api/archive/events/{cid}", json={"full_name": "X"}).status_code == 404
    assert login("cto").patch(f"/api/archive/teams/{team['id']}", json={"award": "X"}).status_code == 404


def test_full_name_reaches_the_public_hall_of_fame(login, org, client, db_session):
    cid, _team = _archived_with_roster(login, org)
    # the public endpoint only publishes competitions
    event = db_session.get(Event, cid)
    event.kind_id = _competition_kind_id(db_session)
    db_session.commit()

    login("cto").patch(f"/api/archive/events/{cid}", json={"full_name": "MATE ROV Competition"})

    record = next(r for r in client.get("/api/public/hall-of-fame").json() if r["id"] == str(cid))
    assert record["fullName"] == "MATE ROV Competition"
    # …and still no PII on the way out
    assert set(record["groups"][0]["members"][0]) == {"name", "role"}


def test_archived_event_row_carries_title_and_awards(login, org):
    cid, _team = _archived_with_roster(login, org)
    login("cto").patch(
        f"/api/archive/events/{cid}", json={"full_name": "Long Title", "awards": ["🥇 1st"]}
    )
    row = next(e for e in login("comp_member").get("/api/archive/events").json() if e["id"] == cid)
    assert row["full_name"] == "Long Title"
    assert row["awards"] == ["🥇 1st"]
    assert row["can_manage"] is False


def test_event_status_untouched_by_record_edits(login, org):
    cid, _team = _archived_with_roster(login, org)
    login("cto").patch(f"/api/archive/events/{cid}", json={"full_name": "X"})
    assert login("cto").get(f"/api/events/{cid}").json()["status"] == EventStatus.ARCHIVED
