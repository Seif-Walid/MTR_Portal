"""Competition-scoped authority. Two ways to act on a competition:

- **High staff** (leadership) — may manage any competition's structure, and
  may create new competitions/teams in the first place (a separate, coarser
  gate from competition-scoped authority — see require_high_staff).
- **Whoever occupies a `grants_management` role position** for that
  competition (or, for a team, that team) — may manage its categories, teams,
  and role assignments. Which role(s) grant this is entirely admin-
  configured (see app/domains/positions/role_engine.py) — there is no
  dedicated "PM"/"lead" concept in this module anymore.

Being an occupant is per-record, so authority never leaks between
competitions.
"""

from fastapi import HTTPException, status as http_status
from sqlalchemy.orm import Session

from app.domains.competitions.models import CompetitionTeam, CompetitionTeamMember
from app.domains.positions.role_engine import can_manage_via_role
from app.domains.users.models import User


def can_manage_competition(db: Session, user: User, competition_id: int) -> bool:
    """A competition's structure (categories, teams, role assignments) is run
    by whoever occupies a grants_management role position for it, plus
    admin/CEO. High staff aren't automatically managers of every
    competition — they create competitions (and are auto-seated in whatever
    role is configured with auto_assign_creator), which is how they get in.
    This keeps authority scoped."""
    return user.is_admin or user.is_ceo or can_manage_via_role(db, user.id, "competition", competition_id)


def can_manage_team(db: Session, user: User, team: CompetitionTeam) -> bool:
    if can_manage_via_role(db, user.id, "team", team.id):
        return True
    return can_manage_competition(db, user, team.category.competition_id)


def require_high_staff(user: User) -> None:
    if not user.is_high_staff:
        raise HTTPException(
            http_status.HTTP_403_FORBIDDEN, "Only senior staff can do this"
        )


def require_manage_competition(db: Session, user: User, competition_id: int) -> None:
    if not can_manage_competition(db, user, competition_id):
        raise HTTPException(
            http_status.HTTP_403_FORBIDDEN,
            "You must manage this competition (or be senior staff).",
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
