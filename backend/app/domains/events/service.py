"""Event-scoped authority, derived entirely from the access ladder:

- **events.manage_any** (in the user's own effective level) — may
  manage any event's structure, no seat needed.
- **A seat whose level includes events.manage_seated** — occupying a
  role position for that event (or, for a team, that team) whose
  *seat* level carries the privilege makes you its manager. It's the seat's
  level that counts, not the person's: a "{event} PM" seat set to a
  managerial level confers management of that event, while merely
  being a "{member}" seat holder somewhere confers nothing — even if the
  person is powerful elsewhere.

Being an occupant is per-record, so authority never leaks between
events.
"""

from fastapi import HTTPException, status as http_status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domains.access import service as access
from app.domains.access.models import AccessLevel
from app.domains.events.models import EventCategory, EventTeam, EventTeamMember, EventKind
from app.domains.positions.models import Position, PositionOccupant
from app.domains.positions.role_engine import occupied_seat_level_ids
from app.domains.users.models import User


def team_member_user_ids(db: Session, team_id: int) -> set[int]:
    """Everyone on an event team: occupants of its team-scoped role seats
    (coach / assistant / lead / member) plus any explicit membership rows.
    Leadership here is expressed through role-seat occupancy, so a team's
    people are not only its EventTeamMember rows."""
    seat_users = set(
        db.scalars(
            select(PositionOccupant.user_id)
            .join(Position, Position.id == PositionOccupant.position_id)
            .where(Position.entity_type == "team", Position.entity_id == team_id)
        )
    )
    membership_users = set(
        db.scalars(select(EventTeamMember.user_id).where(EventTeamMember.team_id == team_id))
    )
    return seat_users | membership_users


def user_seat_entity_ids(db: Session, user_id: int, entity_type: str) -> set[int]:
    """Ids of the entities of `entity_type` on which the user occupies a role
    seat (e.g. every event they hold an event-scoped seat on)."""
    return set(
        db.scalars(
            select(Position.entity_id)
            .join(PositionOccupant, PositionOccupant.position_id == Position.id)
            .where(
                PositionOccupant.user_id == user_id,
                Position.entity_type == entity_type,
                Position.entity_id.is_not(None),
            )
        )
    )


def user_event_team_ids(db: Session, user_id: int) -> set[int]:
    """Event teams the user is on, from three sources:

    - a team-scoped role seat (coach / assistant / lead / member),
    - an explicit membership row, and
    - an *event*-scoped seat (e.g. "{event} PM"), which outranks the team seats
      chained beneath it: holding it puts the user on every team of that event.
    """
    by_seat = user_seat_entity_ids(db, user_id, "team")
    by_membership = set(
        db.scalars(select(EventTeamMember.team_id).where(EventTeamMember.user_id == user_id))
    )
    by_event = set()
    event_ids = user_seat_entity_ids(db, user_id, "event")
    if event_ids:
        by_event = set(
            db.scalars(
                select(EventTeam.id)
                .join(EventCategory, EventCategory.id == EventTeam.category_id)
                .where(
                    EventCategory.event_id.in_(event_ids),
                    EventTeam.deleted_at.is_(None),
                )
            )
        )
    return by_seat | by_membership | by_event

# Sample event kinds — used ONLY by the demo seed (`app.seed --demo`) and the
# test fixtures. A clean install ships with NO event kinds: Events is empty
# until the org defines its own on the site, so Event/Training/R&D are
# the admin's data, never built-in. (slug, name, event_label, category_label,
# team_label, member_label.)
PRESET_KINDS: list[tuple[str, str, str, str, str, str]] = [
    ("competition", "Competition", "Competition", "Category", "Team", "Member"),
    ("training", "Training", "Training Season", "Category", "Group", "Member"),
    ("rnd", "R&D", "Topic", "Category", "Team", "Member"),
]


def ensure_preset_kinds(db: Session) -> None:
    """Creates the sample event kinds if none exist yet — demo/tests only.
    NOT called on a clean install (see app/seed.run)."""
    if db.scalar(select(EventKind.id).limit(1)) is not None:
        return
    for order, (slug, name, ev, cat, team, mem) in enumerate(PRESET_KINDS, start=1):
        db.add(EventKind(
            slug=slug, name=name, event_label=ev, category_label=cat,
            team_label=team, member_label=mem, sort_order=order,
        ))
    db.flush()


def _manages_via_seat(db: Session, user: User, entity_type: str, entity_id: int) -> bool:
    for level_id in occupied_seat_level_ids(db, user.id, entity_type, entity_id):
        level = db.get(AccessLevel, level_id)
        if "events.manage_seated" in access.privileges_of(db, level):
            return True
    return False


def can_manage_event(db: Session, user: User, event_id: int) -> bool:
    if access.has_privilege(db, user, "events.manage_any"):
        return True
    return _manages_via_seat(db, user, "event", event_id)


def can_manage_team(db: Session, user: User, team: EventTeam) -> bool:
    if _manages_via_seat(db, user, "team", team.id):
        return True
    return can_manage_event(db, user, team.category.event_id)


def require_can_create(db: Session, user: User) -> None:
    access.require_privilege(db, user, "events.create")


def require_view(db: Session, user: User) -> None:
    access.require_privilege(db, user, "events.view")


def require_manage_event(db: Session, user: User, event_id: int) -> None:
    if not can_manage_event(db, user, event_id):
        raise HTTPException(
            http_status.HTTP_403_FORBIDDEN,
            "You must manage this event to do that.",
        )


def require_manage_team(db: Session, user: User, team: EventTeam) -> None:
    if not can_manage_team(db, user, team):
        raise HTTPException(
            http_status.HTTP_403_FORBIDDEN,
            "Only this team's managers (or a event manager) can change its members.",
        )


def can_manage_entity(db: Session, user: User, entity_type: str, entity_id: int) -> bool:
    """Dispatch for the generic role-position occupants endpoint
    (positions/router.py), which doesn't itself know that a team's managers
    include its event's managers, or that a membership's managers are
    whoever manages its team — only this domain knows that shape."""
    if entity_type == "event":
        return can_manage_event(db, user, entity_id)
    if entity_type == "team":
        team = db.get(EventTeam, entity_id)
        return team is not None and can_manage_team(db, user, team)
    if entity_type == "membership":
        member = db.get(EventTeamMember, entity_id)
        return member is not None and can_manage_team(db, user, member.team)
    return False
