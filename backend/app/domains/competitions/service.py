"""Competition-scoped authority, derived entirely from the access ladder:

- **competitions.manage_any** (in the user's own effective level) — may
  manage any competition's structure, no seat needed.
- **A seat whose level includes competitions.manage_seated** — occupying a
  role position for that competition (or, for a team, that team) whose
  *seat* level carries the privilege makes you its manager. It's the seat's
  level that counts, not the person's: a "{competition} PM" seat set to a
  managerial level confers management of that competition, while merely
  being a "{member}" seat holder somewhere confers nothing — even if the
  person is powerful elsewhere.

Being an occupant is per-record, so authority never leaks between
competitions.
"""

from fastapi import HTTPException, status as http_status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domains.access import service as access
from app.domains.access.models import AccessLevel
from app.domains.competitions.models import CompetitionTeam, CompetitionTeamMember, EventKind
from app.domains.positions.role_engine import occupied_seat_level_ids
from app.domains.users.models import User

# Sample event kinds — used ONLY by the demo seed (`app.seed --demo`) and the
# test fixtures. A clean install ships with NO event kinds: Events is empty
# until the org defines its own on the site, so Competition/Training/R&D are
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
        if "competitions.manage_seated" in access.privileges_of(db, level):
            return True
    return False


def can_manage_competition(db: Session, user: User, competition_id: int) -> bool:
    if access.has_privilege(db, user, "competitions.manage_any"):
        return True
    return _manages_via_seat(db, user, "competition", competition_id)


def can_manage_team(db: Session, user: User, team: CompetitionTeam) -> bool:
    if _manages_via_seat(db, user, "team", team.id):
        return True
    return can_manage_competition(db, user, team.category.competition_id)


def require_can_create(db: Session, user: User) -> None:
    access.require_privilege(db, user, "competitions.create")


def require_view(db: Session, user: User) -> None:
    access.require_privilege(db, user, "competitions.view")


def require_manage_competition(db: Session, user: User, competition_id: int) -> None:
    if not can_manage_competition(db, user, competition_id):
        raise HTTPException(
            http_status.HTTP_403_FORBIDDEN,
            "You must manage this competition to do that.",
        )


def require_manage_team(db: Session, user: User, team: CompetitionTeam) -> None:
    if not can_manage_team(db, user, team):
        raise HTTPException(
            http_status.HTTP_403_FORBIDDEN,
            "Only this team's managers (or a competition manager) can change its members.",
        )


def can_manage_entity(db: Session, user: User, entity_type: str, entity_id: int) -> bool:
    """Dispatch for the generic role-position occupants endpoint
    (positions/router.py), which doesn't itself know that a team's managers
    include its competition's managers, or that a membership's managers are
    whoever manages its team — only this domain knows that shape."""
    if entity_type == "competition":
        return can_manage_competition(db, user, entity_id)
    if entity_type == "team":
        team = db.get(CompetitionTeam, entity_id)
        return team is not None and can_manage_team(db, user, team)
    if entity_type == "membership":
        member = db.get(CompetitionTeamMember, entity_id)
        return member is not None and can_manage_team(db, user, member.team)
    return False
