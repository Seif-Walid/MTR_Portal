"""The public Hall of Fame endpoint: archived competitions only, PII-free, in the
website's CompetitionRecord shape."""

import datetime

from app.domains.events.models import (
    Event,
    EventCategory,
    EventKind,
    EventStatus,
    EventTeam,
    EventTeamMember,
)
from app.domains.users.models import User


def _competition_kind(db):
    kind = EventKind(
        slug="competition",
        name="Competition",
        event_label="Competition",
        category_label="Category",
        team_label="Team",
        member_label="Member",
        sort_order=1,
    )
    db.add(kind)
    db.flush()
    return kind


def _member(db, name, department):
    u = User(
        email=f"{name.replace(' ', '.').lower()}@x.test",
        full_name=name,
        hashed_password="x",
        department=department,
    )
    db.add(u)
    db.flush()
    return u


def test_hall_of_fame_shape_and_filtering(client, db_session):
    db = db_session
    kind = _competition_kind(db)

    # Archived competition with a per-team award and a member carrying a dept.
    e1 = Event(
        name="MRC 2025",
        kind_id=kind.id,
        start_date=datetime.date(2025, 5, 1),
        status=EventStatus.ARCHIVED,
    )
    db.add(e1)
    db.flush()
    cat = EventCategory(event_id=e1.id, name="Sumo")
    db.add(cat)
    db.flush()
    team = EventTeam(category_id=cat.id, name="Sumo 1", award="🥇 1st Place")
    db.add(team)
    db.flush()
    u = _member(db, "Ahmed Barakat", "electrical")
    db.add(EventTeamMember(team_id=team.id, user_id=u.id))

    # A discipline-less group: category name == team name -> sublabel is dropped.
    e2 = Event(
        name="Fu-Tech Challenge",
        kind_id=kind.id,
        start_date=datetime.date(2024, 3, 1),
        status=EventStatus.ARCHIVED,
        awards=["🥇 1st Place — RC Sumo 1"],
    )
    db.add(e2)
    db.flush()
    cat2 = EventCategory(event_id=e2.id, name="Roster")
    db.add(cat2)
    db.flush()
    db.add(EventTeam(category_id=cat2.id, name="Roster"))

    # An ACTIVE competition must never appear publicly.
    db.add(
        Event(
            name="Active One",
            kind_id=kind.id,
            start_date=datetime.date(2026, 1, 1),
            status=EventStatus.ACTIVE,
        )
    )
    db.commit()

    resp = client.get("/api/public/hall-of-fame")
    assert resp.status_code == 200
    data = resp.json()

    names = [r["event"] for r in data]
    assert "Active One" not in names  # filtering: active excluded
    assert names == ["MRC 2025", "Fu-Tech Challenge"]  # newest first

    mrc = data[0]
    assert mrc["year"] == 2025
    assert mrc["awards"] is None
    grp = mrc["groups"][0]
    assert grp == {
        "label": "Sumo 1",
        "sublabel": "Sumo",
        "award": "🥇 1st Place",
        "members": [{"name": "Ahmed Barakat", "role": "Electrical"}],
    }

    futech = data[1]
    assert futech["awards"] == ["🥇 1st Place — RC Sumo 1"]
    assert futech["groups"][0]["sublabel"] is None  # dropped when == team name


def test_hall_of_fame_leaks_no_pii(client, db_session):
    """The payload must carry only name + role for members — never email,
    user id, department raw value, or any profile field."""
    db = db_session
    kind = _competition_kind(db)
    e = Event(
        name="Robotex 2024",
        kind_id=kind.id,
        start_date=datetime.date(2024, 11, 1),
        status=EventStatus.ARCHIVED,
    )
    db.add(e)
    db.flush()
    cat = EventCategory(event_id=e.id, name="Roster")
    db.add(cat)
    db.flush()
    team = EventTeam(category_id=cat.id, name="Roster")
    db.add(team)
    db.flush()
    u = _member(db, "Seif Walid", "software")
    db.add(EventTeamMember(team_id=team.id, user_id=u.id))
    db.commit()

    member = client.get("/api/public/hall-of-fame").json()[0]["groups"][0]["members"][0]
    assert set(member.keys()) == {"name", "role"}
    assert u.email not in str(member)
