from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select

from app.domains.auth.deps import DB, CurrentUser
from app.domains.competitions.models import (
    Competition,
    CompetitionCategory,
    CompetitionPM,
    CompetitionStatus,
    CompetitionTeam,
    CompetitionTeamMember,
)
from app.domains.competitions.schemas import (
    CategoryCreate,
    CategoryOut,
    CompetitionCreate,
    CompetitionDetailOut,
    CompetitionEdit,
    CompetitionOut,
    MemberAdd,
    MemberOut,
    PMAdd,
    TeamCreate,
    TeamEdit,
    TeamOut,
)
from app.domains.competitions.service import (
    can_manage_competition,
    can_manage_team,
    require_high_staff,
    require_manage_competition,
    require_manage_team,
)
from app.domains.inventory.models import InventoryAllocation
from app.domains.users.models import User
from app.domains.users.schemas import UserBrief

router = APIRouter(prefix="/competitions", tags=["competitions"])


def _resolve_user(db: DB, user_id: int, what: str) -> int:
    if db.get(User, user_id) is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{what} not found")
    return user_id


def _team_out(team: CompetitionTeam, can_manage: bool, user_id: int) -> TeamOut:
    return TeamOut(
        id=team.id,
        name=team.name,
        lead=UserBrief.model_validate(team.lead) if team.lead else None,
        members=[MemberOut(id=m.id, user=UserBrief.model_validate(m.user)) for m in team.members],
        can_manage_members=can_manage or team.lead_id == user_id,
    )


def _counts(comp: Competition) -> tuple[int, int, int]:
    cats = len(comp.categories)
    teams = sum(len(c.teams) for c in comp.categories)
    members = sum(len(t.members) for c in comp.categories for t in c.teams)
    return cats, teams, members


def _base_out(db: DB, comp: Competition, manage: bool) -> dict:
    cats, teams, members = _counts(comp)
    alloc = db.scalar(
        select(func.count()).select_from(InventoryAllocation).where(
            InventoryAllocation.competition_id == comp.id
        )
    ) or 0
    return dict(
        id=comp.id, name=comp.name, status=comp.status, description=comp.description,
        start_date=comp.start_date, end_date=comp.end_date, created_at=comp.created_at,
        pms=[UserBrief.model_validate(pm.user) for pm in comp.pms],
        category_count=cats, team_count=teams, member_count=members, allocation_count=alloc,
        can_manage=manage,
    )


def _list_out(db: DB, user: User, comp: Competition) -> CompetitionOut:
    return CompetitionOut(**_base_out(db, comp, can_manage_competition(db, user, comp.id)))


def _detail_out(db: DB, user: User, comp: Competition) -> CompetitionDetailOut:
    manage = can_manage_competition(db, user, comp.id)
    categories = [
        CategoryOut(
            id=cat.id,
            name=cat.name,
            teams=[_team_out(t, manage, user.id) for t in cat.teams],
        )
        for cat in comp.categories
    ]
    return CompetitionDetailOut(**_base_out(db, comp, manage), categories=categories)


def _get_comp(db: DB, competition_id: int) -> Competition:
    comp = db.get(Competition, competition_id)
    if comp is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Competition not found")
    return comp


def _get_team(db: DB, team_id: int) -> CompetitionTeam:
    team = db.get(CompetitionTeam, team_id)
    if team is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Team not found")
    return team


# --- teams & categories (literal routes, before /{competition_id}) --------
@router.delete("/categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_category(category_id: int, db: DB, user: CurrentUser) -> None:
    cat = db.get(CompetitionCategory, category_id)
    if cat is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Category not found")
    require_manage_competition(db, user, cat.competition_id)
    db.delete(cat)
    db.commit()


@router.post("/categories/{category_id}/teams", status_code=status.HTTP_201_CREATED)
def add_team(category_id: int, payload: TeamCreate, db: DB, user: CurrentUser) -> TeamOut:
    cat = db.get(CompetitionCategory, category_id)
    if cat is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Category not found")
    require_manage_competition(db, user, cat.competition_id)
    team = CompetitionTeam(
        category_id=category_id,
        name=payload.name,
        lead_id=_resolve_user(db, payload.lead_id, "Lead") if payload.lead_id else None,
    )
    db.add(team)
    db.commit()
    db.refresh(team)
    return _team_out(team, True, user.id)


@router.patch("/teams/{team_id}")
def edit_team(team_id: int, payload: TeamEdit, db: DB, user: CurrentUser) -> TeamOut:
    team = _get_team(db, team_id)
    require_manage_competition(db, user, team.category.competition_id)
    if payload.name is not None:
        team.name = payload.name
    if payload.clear_lead:
        team.lead_id = None
    elif payload.lead_id is not None:
        team.lead_id = _resolve_user(db, payload.lead_id, "Lead")
    db.commit()
    db.refresh(team)
    return _team_out(team, True, user.id)


@router.delete("/teams/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_team(team_id: int, db: DB, user: CurrentUser) -> None:
    team = _get_team(db, team_id)
    require_manage_competition(db, user, team.category.competition_id)
    db.delete(team)
    db.commit()


@router.post("/teams/{team_id}/members", status_code=status.HTTP_201_CREATED)
def add_member(team_id: int, payload: MemberAdd, db: DB, user: CurrentUser) -> TeamOut:
    team = _get_team(db, team_id)
    require_manage_team(db, user, team)  # the scoped team lead qualifies here
    _resolve_user(db, payload.user_id, "Member")
    exists = db.scalar(
        select(CompetitionTeamMember).where(
            CompetitionTeamMember.team_id == team_id,
            CompetitionTeamMember.user_id == payload.user_id,
        )
    )
    if exists is None:
        db.add(CompetitionTeamMember(team_id=team_id, user_id=payload.user_id))
        db.commit()
        db.refresh(team)
    return _team_out(team, can_manage_team(db, user, team), user.id)


@router.delete("/teams/{team_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(team_id: int, user_id: int, db: DB, user: CurrentUser) -> None:
    team = _get_team(db, team_id)
    require_manage_team(db, user, team)
    member = db.scalar(
        select(CompetitionTeamMember).where(
            CompetitionTeamMember.team_id == team_id,
            CompetitionTeamMember.user_id == user_id,
        )
    )
    if member is not None:
        db.delete(member)
        db.commit()


# --- competitions ---------------------------------------------------------
@router.get("")
def list_competitions(
    db: DB, user: CurrentUser, include_archived: bool = False
) -> list[CompetitionOut]:
    query = select(Competition)
    if not include_archived:
        query = query.where(Competition.status == CompetitionStatus.ACTIVE)
    comps = db.scalars(query.order_by(Competition.name)).all()
    return [_list_out(db, user, c) for c in comps]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_competition(payload: CompetitionCreate, db: DB, user: CurrentUser) -> CompetitionDetailOut:
    require_high_staff(user)
    if db.scalar(select(Competition).where(Competition.name == payload.name)):
        raise HTTPException(status.HTTP_409_CONFLICT, "A competition with that name already exists")
    comp = Competition(
        name=payload.name,
        description=payload.description,
        start_date=payload.start_date,
        end_date=payload.end_date,
    )
    db.add(comp)
    db.flush()
    db.add(CompetitionPM(competition_id=comp.id, user_id=user.id))  # creator is a PM
    db.commit()
    db.refresh(comp)
    return _detail_out(db, user, comp)


@router.get("/{competition_id}")
def get_competition(competition_id: int, db: DB, user: CurrentUser) -> CompetitionDetailOut:
    return _detail_out(db, user, _get_comp(db, competition_id))


@router.patch("/{competition_id}")
def edit_competition(
    competition_id: int, payload: CompetitionEdit, db: DB, user: CurrentUser
) -> CompetitionOut:
    require_manage_competition(db, user, competition_id)
    comp = _get_comp(db, competition_id)
    if payload.name is not None and payload.name != comp.name:
        if db.scalar(select(Competition).where(Competition.name == payload.name)):
            raise HTTPException(status.HTTP_409_CONFLICT, "A competition with that name already exists")
        comp.name = payload.name
    if payload.description is not None:
        comp.description = payload.description
    if payload.status is not None:
        comp.status = payload.status
    comp.start_date = None if payload.clear_start_date else (payload.start_date or comp.start_date)
    comp.end_date = None if payload.clear_end_date else (payload.end_date or comp.end_date)
    db.commit()
    db.refresh(comp)
    return _list_out(db, user, comp)


@router.delete("/{competition_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_competition(competition_id: int, db: DB, user: CurrentUser) -> None:
    require_manage_competition(db, user, competition_id)
    comp = _get_comp(db, competition_id)
    in_use = db.scalar(
        select(func.count()).select_from(InventoryAllocation).where(
            InventoryAllocation.competition_id == competition_id
        )
    )
    if in_use:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"{in_use} allocation(s) reference this competition — archive it instead.",
        )
    db.delete(comp)
    db.commit()


# --- project managers -----------------------------------------------------
@router.post("/{competition_id}/pms", status_code=status.HTTP_201_CREATED)
def add_pm(competition_id: int, payload: PMAdd, db: DB, user: CurrentUser) -> CompetitionDetailOut:
    require_high_staff(user)  # leadership appoints the PMs
    comp = _get_comp(db, competition_id)
    _resolve_user(db, payload.user_id, "Project manager")
    exists = db.scalar(
        select(CompetitionPM).where(
            CompetitionPM.competition_id == competition_id,
            CompetitionPM.user_id == payload.user_id,
        )
    )
    if exists is None:
        db.add(CompetitionPM(competition_id=competition_id, user_id=payload.user_id))
        db.commit()
        db.refresh(comp)
    return _detail_out(db, user, comp)


@router.delete("/{competition_id}/pms/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_pm(competition_id: int, user_id: int, db: DB, user: CurrentUser) -> None:
    require_high_staff(user)
    pm = db.scalar(
        select(CompetitionPM).where(
            CompetitionPM.competition_id == competition_id,
            CompetitionPM.user_id == user_id,
        )
    )
    if pm is not None:
        db.delete(pm)
        db.commit()


# --- categories (nested under a competition) ------------------------------
@router.post("/{competition_id}/categories", status_code=status.HTTP_201_CREATED)
def add_category(competition_id: int, payload: CategoryCreate, db: DB, user: CurrentUser) -> CategoryOut:
    require_manage_competition(db, user, competition_id)
    _get_comp(db, competition_id)
    cat = CompetitionCategory(competition_id=competition_id, name=payload.name)
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return CategoryOut(id=cat.id, name=cat.name, teams=[])
