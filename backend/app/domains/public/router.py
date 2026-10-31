"""Public, unauthenticated read API for the marketing website.

This is the ONLY surface the public website (mindtechrobotics.com) may call.
Everything it *returns* is deliberately anonymous and PII-free: it exposes a
member's public name and technical discipline and nothing else — never the
contact, national-ID, guardian, birthday or any other roster field, and
never a user id or email. Treat this router as published-to-the-world.

The one write is the join form: POST /applications takes an applicant's
answers in and answers only "received" — nothing stored is ever read back out
here (reviewers read applications through the authenticated /applications).
An application can name an event from /events that is open for applications,
which is how the site offers "join MATE ROV 2027" instead of a generic form.

People is the public projection of the Organization chart: each real seat's
title and the public names of whoever holds it, with the events each of them
coached or ran — the website's People page reads this instead of a hand-kept
list.

Events is what is running now, and which of it is recruiting.

The Hall of Fame is the public projection of the portal's *archived competition*
events: the same records the internal Archive is built from, shaped exactly like
the website's existing `CompetitionRecord` so the site can consume it directly.
The record shape itself lives in app/domains/events/hall_of_fame.py, shared with
the Archive so the two views can never drift.
"""

from collections import defaultdict

from fastapi import APIRouter, Request, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.database import DB
from app.domains.applications import service as applications
from app.domains.applications.schemas import ApplicationIn
from app.domains.events.hall_of_fame import archived_competitions, record_out, summary
from app.domains.events.models import Event, EventSeatRecord, EventStatus, EventTeam
from app.domains.positions import role_engine
from app.domains.positions.models import Position

router = APIRouter(prefix="/public", tags=["public"])


@router.get("/hall-of-fame")
def hall_of_fame(db: DB) -> list[dict]:
    """Every archived competition, newest first, in the website's CompetitionRecord
    shape: {id, event, fullName, year, awards, groups[{label, sublabel, award,
    members[{name, role}]}]}. Unauthenticated and PII-free."""
    return [record_out(event) for event in db.scalars(archived_competitions()).all()]


@router.get("/hall-of-fame/summary")
def hall_of_fame_summary(db: DB) -> dict:
    """What the record adds up to: competitions entered, seasons, members
    fielded, and the medal tally — counted from the same archived competitions
    /hall-of-fame returns, so the headline numbers can never disagree with the
    records printed underneath them."""
    return summary(list(db.scalars(archived_competitions()).all()))


@router.get("/people")
def people(db: DB) -> list[dict]:
    """The Organization chart as the website shows it: a tree of
    {title, technical, people[{name, coached[...]}], children[...]}.

    Only real seats marked "on website" — roster seats ("Software member") are
    kept off by default, so members are never listed; a hidden seat's own
    sub-seats move up to its parent rather than vanishing. The automatic
    per-event role seats are not seats here either: they are what each person
    `coached` (see _coaching). Only active accounts' names. Someone holding
    several seats appears under each. Unauthenticated and PII-free: a seat
    title, a name, and the events they ran — nothing else."""
    positions = list(db.scalars(
        select(Position)
        .where(Position.role_template_id.is_(None))
        .options(selectinload(Position.occupants))
    ))
    children: dict[int | None, list[Position]] = defaultdict(list)
    real_ids = {p.id for p in positions}
    for p in positions:
        children[p.parent_id if p.parent_id in real_ids else None].append(p)

    shown_ids = {u.id for p in positions if p.on_website for u in p.occupants if u.is_active}
    coached = _coaching(db, shown_ids)

    def build(p: Position) -> list[dict]:
        kids = [
            node
            for c in sorted(children.get(p.id, []), key=lambda c: c.title.lower())
            for node in build(c)
        ]
        if not p.on_website:
            return kids
        return [{
            "title": p.title.strip(),
            "technical": p.is_technical,
            "people": [
                {"name": u.full_name, "coached": coached.get(u.id, [])}
                for u in p.occupants if u.is_active
            ],
            "children": kids,
        }]

    return [
        node
        for p in sorted(children.get(None, []), key=lambda c: c.title.lower())
        for node in build(p)
    ]


def _seat(role: str, event: Event, team: EventTeam | None) -> dict:
    return {
        "as": role[:1].upper() + role[1:],
        "event": event.name,
        "kind": event.kind.slug if event.kind else None,
        "year": event.start_date.year if event.start_date else None,
        "active": event.status == EventStatus.ACTIVE,
        "team": team.path_name if team is not None else None,
    }


def _is_roster(role: str) -> bool:
    """A seat for a team's members ("{team} member") — the same rule that keeps
    roster seats off the People page — is competing, not coaching."""
    return "member" in role.lower()


def _coaching(db: DB, user_ids: set[int]) -> dict[int, list[dict]]:
    """The events each person ran rather than competed in — a PM, a coach, an
    instructor — read off the automatic role seats: the live ones for active
    events, and the record archiving kept for finished ones. Roster seats (a
    team's members) are left out: competing is the Hall of Fame's business.
    Newest event first."""
    out: dict[int, list[tuple[tuple, dict]]] = defaultdict(list)
    if not user_ids:
        return {}

    seats = db.scalars(
        select(Position)
        .where(
            Position.role_template_id.is_not(None),
            Position.entity_type.in_(("event", "team")),
        )
        .options(selectinload(Position.occupant_links))
    )
    for pos in seats:
        holders = [link.user_id for link in pos.occupant_links if link.user_id in user_ids]
        if not holders or pos.role_template is None:
            continue
        role = role_engine.role_name(pos.role_template.title_template)
        if _is_roster(role):
            continue
        team = db.get(EventTeam, pos.entity_id) if pos.entity_type == "team" else None
        if pos.entity_type == "team" and (team is None or team.deleted_at is not None):
            continue
        event = team.category.event if team is not None else db.get(Event, pos.entity_id)
        if event is None or not role:
            continue
        for uid in holders:
            out[uid].append(((pos.role_template.sort_order or 0,), _seat(role, event, team)))

    records = db.scalars(
        select(EventSeatRecord).where(EventSeatRecord.user_id.in_(user_ids))
    )
    for r in records:
        event = db.get(Event, r.event_id)
        team = db.get(EventTeam, r.team_id) if r.team_id is not None else None
        if event is None or not r.role or _is_roster(r.role):
            continue
        out[r.user_id].append(((r.sort_order,), _seat(r.role, event, team)))

    def newest_first(item: tuple[tuple, dict]):
        order, seat = item
        return (-(seat["year"] or 0), seat["event"].lower(), order, seat["team"] or "")

    result: dict[int, list[dict]] = {}
    for uid, items in out.items():
        seen: set[tuple] = set()
        result[uid] = []
        for _, seat in sorted(items, key=newest_first):
            key = (seat["as"], seat["event"], seat["team"])
            if key not in seen:
                seen.add(key)
                result[uid].append(seat)
    return result


@router.get("/events")
def events(db: DB) -> list[dict]:
    """The events running now — competitions being prepared for, training
    seasons, R&D topics — soonest first, with whether each is taking
    applications from the site's join form. Finished events are the Hall of
    Fame's (/hall-of-fame). Unauthenticated: a name, its kind, dates, a place
    and the public pitch; never the internal description, budget or roster."""
    rows = db.scalars(
        select(Event)
        .where(Event.status == EventStatus.ACTIVE)
        .order_by(Event.start_date.asc().nullslast(), Event.name)
    )
    return [
        {
            "id": e.id,
            "name": e.name,
            "fullName": e.full_name,
            "kind": (
                {
                    "slug": e.kind.slug,
                    "name": e.kind.name,
                    "label": e.kind.event_label,
                    "teamLabel": e.kind.team_label,
                }
                if e.kind else None
            ),
            "summary": e.public_summary,
            "startDate": e.start_date.isoformat() if e.start_date else None,
            "endDate": e.end_date.isoformat() if e.end_date else None,
            "location": e.location,
            "applicationsOpen": e.applications_open,
        }
        for e in rows
    ]


@router.post("/applications", status_code=status.HTTP_201_CREATED)
def apply(payload: ApplicationIn, request: Request, db: DB) -> dict:
    """The website's "Join the team" form. Unauthenticated; rate-limited per
    connection, with a honeypot field for bots. Sending again within a day
    updates the earlier application rather than adding another."""
    applications.submit(db, payload, applications.client_hash(request))
    return {"received": True}
