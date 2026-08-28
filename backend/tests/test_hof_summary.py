"""The Hall-of-Fame overview: the headline numbers the website prints above the
records, counted from the records themselves rather than kept by hand."""

from datetime import date

from app.domains.events.models import Event
from tests.test_archive_record import _archived_with_roster, _competition_kind_id


def _published(login, org, db_session, year: int = 2025):
    """An archived competition, dated — only that kind is part of the public
    record, and its season is the year it ran."""
    cid, team = _archived_with_roster(login, org)
    event = db_session.get(Event, cid)
    event.kind_id = _competition_kind_id(db_session)
    event.start_date = date(year, 4, 1)
    db_session.commit()
    return cid, team


def test_summary_counts_medals_at_both_levels(login, org, db_session, client):
    """An event either announces its placements itself or leaves them on its
    teams; both conventions count."""
    cid, team = _published(login, org, db_session)
    login("cto").patch(
        f"/api/archive/events/{cid}",
        json={"awards": ["🥇 1st Place — Sumo 1", "🥉 3rd Place — Line 2", "8th Place — Pioneer"]},
    )
    login("cto").patch(f"/api/archive/teams/{team['id']}", json={"award": "🥈 2nd Place"})

    s = login("comp_member").get("/api/archive/summary").json()
    assert (s["gold"], s["silver"], s["bronze"]) == (1, 1, 1)
    # a placement off the podium is on the record but not in the tally
    assert s["special"] == 0
    assert s["competitions"] == 1
    assert s["seasons"] == 1


def test_judged_awards_count_as_special(login, org, db_session, client):
    cid, _team = _published(login, org, db_session)
    login("cto").patch(
        f"/api/archive/events/{cid}", json={"awards": ["🏆 Best Documentation Award"]}
    )

    s = login("comp_member").get("/api/archive/summary").json()
    assert s["special"] == 1
    assert (s["gold"], s["silver"], s["bronze"]) == (0, 0, 0)


def test_members_fielded_counts_each_person_once(login, org, db_session, client):
    """Two members on one roster — a head count of people, not of seats."""
    _cid, _team = _published(login, org, db_session)
    assert login("comp_member").get("/api/archive/summary").json()["members_fielded"] == 2


def test_portal_and_website_see_the_same_numbers(login, org, db_session, client):
    """The portal's overview and the public one are the same projection — if
    they could drift, the site would print a number the portal can't explain."""
    cid, team = _published(login, org, db_session)
    login("cto").patch(f"/api/archive/events/{cid}", json={"awards": ["🥇 1st Place"]})
    login("cto").patch(f"/api/archive/teams/{team['id']}", json={"award": "🥈 2nd Place"})

    assert client.get("/api/public/hall-of-fame/summary").json() == login("comp_member").get(
        "/api/archive/summary"
    ).json()


def test_summary_is_open_to_every_member(login, org, db_session):
    """Like the archived-events list it heads, the overview has no privilege
    gate — it is the club's own record of itself."""
    _published(login, org, db_session)
    assert login("comp_member").get("/api/archive/summary").status_code == 200
