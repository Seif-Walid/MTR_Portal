"""Who took part in an event — derived, never typed.

An event's people are already known: its team memberships (EventTeamMember,
with their competition role), its team- and event-scoped role seats (coach,
lead, PM …) and, once archived, the frozen seat record. Participation is read
from those. The member database's imported `event_participations` rows are
history: they still fill in people the teams don't know about (registrations,
trainings run before the portal had teams) and lend their rating / registration
date to people who are on a team, but nothing new is entered there."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domains.events.models import (
    Event,
    EventCategory,
    EventParticipation,
    EventSeatRecord,
    EventTeam,
    EventTeamMember,
)
from app.domains.positions.models import Position, PositionOccupant
from app.domains.users.models import User


@dataclass
class Participation:
    event: Event
    member: User
    role: str | None = None
    team: str | None = None
    team_id: int | None = None
    mentor: str | None = None
    rating: str | None = None
    registered_at: datetime | None = None
    source: str = "team"  # team | seat | record
    record_id: int | None = None  # the imported row, when there is one


def participations(db: Session, *, event_ids: set[int] | None = None,
                   member_id: int | None = None) -> list[Participation]:
    """Every (event, person) part, one per pair. Filter by events and/or member."""
    teams = {
        t.id: (t, ev_id)
        for t, ev_id in db.execute(
            select(EventTeam, EventCategory.event_id)
            .join(EventCategory, EventCategory.id == EventTeam.category_id)
            .where(EventTeam.deleted_at.is_(None))
        )
        if event_ids is None or ev_id in event_ids
    }
    events = {e.id: e for e in db.scalars(select(Event))}
    users: dict[int, User] = {}

    def user(uid: int) -> User | None:
        if uid not in users:
            users[uid] = db.get(User, uid)
        return users[uid]

    found: dict[tuple[int, int], Participation] = {}
    roles: dict[tuple[int, int], list[str]] = defaultdict(list)

    def add(ev_id: int, uid: int | None, role: str | None, team: EventTeam | None, source: str) -> None:
        if uid is None or (member_id is not None and uid != member_id):
            return
        if event_ids is not None and ev_id not in event_ids:
            return
        ev, u = events.get(ev_id), user(uid)
        if ev is None or u is None:
            return
        key = (ev_id, uid)
        p = found.get(key)
        if p is None:
            p = found[key] = Participation(event=ev, member=u, source=source)
        if team is not None and p.team_id is None:
            p.team_id, p.team = team.id, team.path_name
        if role and role not in roles[key]:
            roles[key].append(role)

    q = select(EventTeamMember).where(EventTeamMember.team_id.in_(teams))
    if member_id is not None:
        q = q.where(EventTeamMember.user_id == member_id)
    for m in db.scalars(q):
        team, ev_id = teams[m.team_id]
        add(ev_id, m.user_id, m.role, team, "team")

    team_of_event: dict[int, list[int]] = defaultdict(list)
    for tid, (_t, ev_id) in teams.items():
        team_of_event[ev_id].append(tid)
    seat_q = (
        select(Position.entity_type, Position.entity_id, Position.title, PositionOccupant.user_id)
        .join(PositionOccupant, PositionOccupant.position_id == Position.id)
        .where(Position.entity_type.in_(("team", "event")))
    )
    if member_id is not None:
        seat_q = seat_q.where(PositionOccupant.user_id == member_id)
    for etype, eid, title, uid in db.execute(seat_q):
        if etype == "team" and eid in teams:
            team, ev_id = teams[eid]
            add(ev_id, uid, _strip(title, team.name), team, "seat")
        elif etype == "event" and eid in events:
            add(eid, uid, _strip(title, events[eid].name), None, "seat")

    rec_q = select(EventSeatRecord)
    if member_id is not None:
        rec_q = rec_q.where(EventSeatRecord.user_id == member_id)
    for r in db.scalars(rec_q):
        add(r.event_id, r.user_id, r.role, teams[r.team_id][0] if r.team_id in teams else None, "seat")

    for key, rs in roles.items():
        found[key].role = " · ".join(rs)

    # the imported record: fills the gaps, never overrides what the teams say
    imp_q = select(EventParticipation)
    if member_id is not None:
        imp_q = imp_q.where(EventParticipation.member_id == member_id)
    if event_ids is not None:
        imp_q = imp_q.where(EventParticipation.event_id.in_(event_ids))
    for r in db.scalars(imp_q):
        key = (r.event_id, r.member_id)
        p = found.get(key)
        if p is None:
            found[key] = Participation(
                event=r.event, member=r.member, role=r.role, team=r.team, mentor=r.mentor,
                rating=r.rating, registered_at=r.registered_at, source="record", record_id=r.id,
            )
            continue
        p.record_id, p.rating, p.registered_at = r.id, r.rating, r.registered_at
        p.mentor = p.mentor or r.mentor
        p.role = p.role or r.role
    return list(found.values())


def _strip(title: str, name: str) -> str:
    """A seat title without its event/team name: "ROV27 coach" → "coach"."""
    t = title.replace(name, "").strip(" -—·:")
    return t or title


def by_member(db: Session) -> dict[int, list[Participation]]:
    out: dict[int, list[Participation]] = defaultdict(list)
    for p in participations(db):
        out[p.member.id].append(p)
    return out
