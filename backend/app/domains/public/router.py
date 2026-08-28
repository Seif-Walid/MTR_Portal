"""Public, unauthenticated read API for the marketing website.

This is the ONLY surface the public website (mindtechrobotics.com) may call.
Everything here is deliberately anonymous and PII-free: it exposes a member's
public name and technical discipline and nothing else — never the contact,
national-ID, guardian, birthday or any other MemberProfile field, and never a
user id or email. Treat this router as published-to-the-world.

The Hall of Fame is the public projection of the portal's *archived competition*
events: the same records the internal Archive is built from, shaped exactly like
the website's existing `CompetitionRecord` so the site can consume it directly.
The record shape itself lives in app/domains/events/hall_of_fame.py, shared with
the Archive so the two views can never drift.
"""

from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.database import DB
from app.domains.events.hall_of_fame import record_out
from app.domains.events.models import (
    Event,
    EventCategory,
    EventKind,
    EventStatus,
    EventTeam,
)

router = APIRouter(prefix="/public", tags=["public"])

# The kind whose archived events make up the Hall of Fame. Training seasons and
# R&D topics are internal — only competitions are shown publicly.
COMPETITION_KIND_SLUG = "competition"


@router.get("/hall-of-fame")
def hall_of_fame(db: DB) -> list[dict]:
    """Every archived competition, newest first, in the website's CompetitionRecord
    shape: {id, event, fullName, year, awards, groups[{label, sublabel, award,
    members[{name, role}]}]}. Unauthenticated and PII-free."""
    events = db.scalars(
        select(Event)
        .join(EventKind, Event.kind_id == EventKind.id)
        .where(
            Event.status == EventStatus.ARCHIVED,
            EventKind.slug == COMPETITION_KIND_SLUG,
        )
        .order_by(Event.start_date.desc().nullslast(), Event.name)
        .options(
            selectinload(Event.categories)
            .selectinload(EventCategory.teams)
            .selectinload(EventTeam.members)
        )
    ).all()

    return [record_out(event) for event in events]
