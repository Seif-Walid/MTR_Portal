"""The Hall-of-Fame projection of an event: its roster of teams and members.

One shared shaping of the record so the two places that show it can never drift:

  * the public website, via /api/public/hall-of-fame (archived competitions only)
  * the portal's own Archive page, via /api/archive/events/{id}

The Archive is the source of truth — the website only reads this projection — so
whatever the site can display has to be visible and editable in the portal too.

Everything here is PII-free by construction: a member contributes their public
name and their verbatim competition role, nothing else.
"""

from app.domains.events.models import Event, EventTeam, EventTeamMember


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
