"""Public, unauthenticated read API for the marketing website.

This is the ONLY surface the public website (mindtechrobotics.com) may call.
Everything here is deliberately anonymous and PII-free: it exposes a member's
public name and technical discipline and nothing else — never the contact,
national-ID, guardian, birthday or any other MemberProfile field, and never a
user id or email. Treat this router as published-to-the-world.

The Hall of Fame is the public projection of the portal's *archived competition*
events: the same records the internal Archive is built from, shaped exactly like
the website's existing `CompetitionRecord` so the site can consume it directly.
"""

from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.database import DB
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


def _role_of(department: str | None) -> str | None:
    """A member's public technical role is their org department, title-cased
    for display ("electrical" -> "Electrical"). No department -> no role shown."""
    return department.title() if department else None


def _member_out(name: str, department: str | None) -> dict:
    # Only the two public fields. Anything else on the user/profile stays server-side.
    return {"name": name, "role": _role_of(department)}


def _year_of(event: Event) -> int | None:
    for d in (event.start_date, event.end_date):
        if d is not None:
            return d.year
    return None


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

    records: list[dict] = []
    for event in events:
        groups: list[dict] = []
        for category in event.categories:
            for team in category.teams:
                if team.deleted_at is not None:
                    continue
                # Groups seeded from a discipline-less roster live under a
                # category named the same as the team; surface that as no
                # sublabel rather than a redundant repeat of the team name.
                sublabel = None if category.name == team.name else category.name
                groups.append(
                    {
                        "label": team.name,
                        "sublabel": sublabel,
                        "award": team.award,
                        "members": [
                            _member_out(m.user.full_name, m.user.department)
                            for m in team.members
                        ],
                    }
                )
        records.append(
            {
                "id": str(event.id),
                "event": event.name,
                "fullName": None,
                "year": _year_of(event),
                "awards": event.awards or None,
                "groups": groups,
            }
        )
    return records
