"""Public, unauthenticated read API for the marketing website.

This is the ONLY surface the public website (mindtechrobotics.com) may call.
Everything it *returns* is deliberately anonymous and PII-free: it exposes a
member's public name and technical discipline and nothing else — never the
contact, national-ID, guardian, birthday or any other MemberProfile field, and
never a user id or email. Treat this router as published-to-the-world.

The one write is the join form: POST /applications takes an applicant's
answers in and answers only "received" — nothing stored is ever read back out
here (reviewers read applications through the authenticated /applications).

People is the public projection of the Organization chart: each real seat's
title and the public names of whoever holds it — the website's team / people
section reads this instead of a hand-kept list.

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
    {title, technical, people[{name}], children[...]}. Only real seats — the
    automatic per-event role seats (a team's lead, its members) are left out,
    they're the Hall of Fame's business — and only active accounts' names.
    Someone holding several seats appears under each. Unauthenticated and
    PII-free: a seat title and a name, nothing else."""
    positions = list(db.scalars(
        select(Position)
        .where(Position.role_template_id.is_(None))
        .options(selectinload(Position.occupants))
    ))
    children: dict[int | None, list[Position]] = defaultdict(list)
    real_ids = {p.id for p in positions}
    for p in positions:
        children[p.parent_id if p.parent_id in real_ids else None].append(p)

    def build(p: Position) -> dict:
        kids = sorted(children.get(p.id, []), key=lambda c: c.title.lower())
        return {
            "title": p.title,
            "technical": p.is_technical,
            "people": [{"name": u.full_name} for u in p.occupants if u.is_active],
            "children": [build(c) for c in kids],
        }

    return [build(p) for p in sorted(children.get(None, []), key=lambda c: c.title.lower())]


@router.post("/applications", status_code=status.HTTP_201_CREATED)
def apply(payload: ApplicationIn, request: Request, db: DB) -> dict:
    """The website's "Join the team" form. Unauthenticated; rate-limited per
    connection, with a honeypot field for bots. Sending again within a day
    updates the earlier application rather than adding another."""
    applications.submit(db, payload, applications.client_hash(request))
    return {"received": True}
