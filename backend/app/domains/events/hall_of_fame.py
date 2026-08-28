"""The Hall-of-Fame projection of an event: its roster of teams and members.

One shared shaping of the record so the two places that show it can never drift:

  * the public website, via /api/public/hall-of-fame (archived competitions only)
  * the portal's own Archive page, via /api/archive/events/{id}

The Archive is the source of truth — the website only reads this projection — so
whatever the site can display has to be visible and editable in the portal too.

Everything here is PII-free by construction: a member contributes their public
name and their verbatim competition role, nothing else.
"""

import re

from sqlalchemy import Select, select
from sqlalchemy.orm import selectinload

from app.domains.events.models import (
    Event,
    EventCategory,
    EventKind,
    EventStatus,
    EventTeam,
    EventTeamMember,
)

# The kind whose archived events make up the Hall of Fame. Training seasons and
# R&D topics are internal — only competitions are part of the public record.
COMPETITION_KIND_SLUG = "competition"


def archived_competitions() -> Select[tuple[Event]]:
    """Every archived competition, newest first, with its roster preloaded.

    Shared so the public record and the portal's overview of it are the same
    set of events by construction."""
    return (
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
    )


def _member_out(member: EventTeamMember, with_ids: bool) -> dict:
    # Only the two public fields. `role` is the member's verbatim competition
    # role (EventTeamMember.role), NOT their department — competition credit is
    # per-event and free-form. Everything else on the user/profile stays server-side.
    out = {"name": member.user.full_name, "role": member.role}
    if with_ids:
        # The membership row id, so the Archive can edit the role in place. Not
        # the user id — that never leaves the server on this projection.
        out["id"] = member.id
    return out


def _group_out(category_name: str, team: EventTeam, with_ids: bool) -> dict:
    # Groups seeded from a discipline-less roster live under a category named
    # the same as the team; surface that as no sublabel rather than a redundant
    # repeat of the team name.
    sublabel = None if category_name == team.name else category_name
    out = {
        "label": team.name,
        "sublabel": sublabel,
        "award": team.award,
        "members": [_member_out(m, with_ids) for m in team.members],
    }
    if with_ids:
        out["id"] = team.id
    return out


def event_groups(event: Event, with_ids: bool = False) -> list[dict]:
    """Every live team in the event as a Hall-of-Fame group, category order.

    `with_ids` adds the team and membership row ids — needed by the Archive so
    it can edit a placement or a role in place, and deliberately left out of the
    public projection."""
    return [
        _group_out(category.name, team, with_ids)
        for category in event.categories
        for team in category.teams
        if team.deleted_at is None
    ]


def year_of(event: Event) -> int | None:
    for d in (event.start_date, event.end_date):
        if d is not None:
            return d.year
    return None


def record_out(event: Event) -> dict:
    """One event in the website's `CompetitionRecord` shape."""
    return {
        "id": str(event.id),
        "event": event.name,
        "fullName": event.full_name,
        "year": year_of(event),
        "awards": event.awards or None,
        "groups": event_groups(event),
    }


# ---------------------------------------------------------------------------
# The overview: what the whole record adds up to.
#
# Awards are free-form strings written the way the team announces them
# ("🥇 1st Place — Sumo 1", "🏆 Best Documentation Award"), at two levels: the
# event (Event.awards) and the individual team (EventTeam.award). Counting them
# is a projection like any other, so it lives here rather than being typed by
# hand into the website — that copy drifted the moment a new medal was won.
# ---------------------------------------------------------------------------

# "1st Place", "2nd place", "3RD PLACE" — the placement inside an award string.
_PLACEMENT = re.compile(r"\b(\d+)\s*(?:st|nd|rd|th)\b", re.IGNORECASE)


def _placement(award: str) -> int | None:
    """The finishing position an award announces, or None if it announces no
    position at all (a named award like "Best Documentation")."""
    match = _PLACEMENT.search(award)
    return int(match.group(1)) if match else None


def _awards_of(event: Event) -> list[str]:
    """Every award the event won, at both levels. An event either carries its
    placements itself or leaves them on its teams; counting both means neither
    convention is silently worth nothing."""
    return [*(event.awards or []), *(t["award"] for t in event_groups(event) if t["award"])]


def summary(events: list[Event]) -> dict:
    """What a set of Hall-of-Fame events adds up to: how much was entered, how
    many people it took, and the medal tally.

    `special` counts awards that name no placement — a judged award like Best
    Documentation is a result, not a nothing, so it is never dropped. Placements
    past the podium are counted in neither: they are visible on the record
    itself, which is where they belong."""
    names: set[str] = set()
    years: set[int] = set()
    medals = {"gold": 0, "silver": 0, "bronze": 0, "special": 0}
    podium = {1: "gold", 2: "silver", 3: "bronze"}

    for event in events:
        year = year_of(event)
        if year is not None:
            years.add(year)
        for group in event_groups(event):
            for member in group["members"]:
                # One person on three teams is one member fielded.
                names.add(member["name"].strip().lower())
        for award in _awards_of(event):
            place = _placement(award)
            if place is None:
                medals["special"] += 1
            elif place in podium:
                medals[podium[place]] += 1

    return {
        "competitions": len(events),
        "seasons": len(years),
        "members_fielded": len(names),
        **medals,
    }
