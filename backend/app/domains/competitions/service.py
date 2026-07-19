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
from sqlalchemy.orm import Session

from app.domains.access import service as access
from app.domains.access.models import AccessLevel
from app.domains.competitions.models import CompetitionTeam, CompetitionTeamMember
from app.domains.positions.role_engine import occupied_seat_level_ids
from app.domains.users.models import User


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
