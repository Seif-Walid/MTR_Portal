"""Competition-scoped authority. Two ways to act on a competition:

- **High staff** (leadership) — may manage any competition's structure.
- **Project Manager** of *that* competition — may manage its categories, teams,
  and team leads.
- **Team Lead** of *that* team — may manage only their own team's members.

Being a lead or PM is per-record, so authority never leaks between competitions.
"""

from fastapi import HTTPException, status as http_status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domains.competitions.models import CompetitionPM, CompetitionTeam
from app.domains.users.models import User


def is_pm(db: Session, user: User, competition_id: int) -> bool:
    return db.scalar(
        select(CompetitionPM.id).where(
            CompetitionPM.competition_id == competition_id,
            CompetitionPM.user_id == user.id,
        )
    ) is not None


def can_manage_competition(db: Session, user: User, competition_id: int) -> bool:
    """A competition's structure (categories, teams, leads) is run by its PMs,
    plus admin/CEO. High staff aren't automatically managers of every
    competition — they create competitions and appoint the PMs (and are made a
    PM on creation), which is how they get in. This keeps authority scoped."""
    return user.is_admin or user.is_ceo or is_pm(db, user, competition_id)


def can_manage_team(db: Session, user: User, team: CompetitionTeam) -> bool:
    if team.lead_id == user.id:  # the scoped team lead
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
            "You must be a project manager of this competition (or senior staff).",
        )


def require_manage_team(db: Session, user: User, team: CompetitionTeam) -> None:
    if not can_manage_team(db, user, team):
        raise HTTPException(
            http_status.HTTP_403_FORBIDDEN,
            "Only this team's lead (or a competition manager) can change its members.",
        )
