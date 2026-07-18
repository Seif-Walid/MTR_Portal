from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select

from app.domains.audit.service import log as audit_log
from app.domains.auth.deps import DB, CurrentUser
from app.domains.competitions.models import (
    Competition,
    CompetitionCategory,
    CompetitionStatus,
    CompetitionTeam,
    CompetitionTeamMember,
)
from app.domains.competitions.role_sync import (
    lineage_for_competition,
    lineage_for_membership,
    lineage_for_team,
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
from app.domains.positions import role_engine
from app.domains.positions.schemas import EntityRoleOut
from app.domains.positions.service import resync_managers
from app.domains.users.models import User
from app.domains.users.schemas import UserBrief

router = APIRouter(prefix="/competitions", tags=["competitions"])


def _resolve_user(db: DB, user_id: int, what: str) -> int:
    if db.get(User, user_id) is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{what} not found")
    return user_id


def _entity_roles_out(db: DB, event: str, entity_type: str, entity_id: int, names: dict[str, str]) -> list[EntityRoleOut]:
    return [
        EntityRoleOut(
            template_id=r["template_id"], title=r["title"], position_id=r["position_id"],
            occupants=[UserBrief.model_validate(u) for u in r["occupants"]],
        )
        for r in role_engine.entity_roles(db, event, entity_type, entity_id, names)
    ]


def _team_out(db: DB, comp: Competition, team: CompetitionTeam, can_manage: bool, user: User) -> TeamOut:
    names = {"competition": comp.name, "team": team.name}
    return TeamOut(
        id=team.id,
        name=team.name,
        roles=_entity_roles_out(db, "team_created", "team", team.id, names),
        members=[MemberOut(id=m.id, user=UserBrief.model_validate(m.user)) for m in team.members],
        can_manage_members=can_manage or can_manage_team(db, user, team),
    )


def _active_teams(cat: CompetitionCategory) -> list[CompetitionTeam]:
    return [t for t in cat.teams if t.deleted_at is None]


def _counts(comp: Competition) -> tuple[int, int, int]:
    cats = len(comp.categories)
    active = [_active_teams(c) for c in comp.categories]
    teams = sum(len(ts) for ts in active)
    members = sum(len(t.members) for ts in active for t in ts)
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
        roles=_entity_roles_out(db, "competition_created", "competition", comp.id, {"competition": comp.name}),
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
            teams=[_team_out(db, comp, t, manage, user) for t in _active_teams(cat)],
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
    if team is None or team.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Team not found")
    return team


def _team_competition(team: CompetitionTeam) -> Competition:
    return team.category.competition


# --- teams & categories (literal routes, before /{competition_id}) --------
@router.delete("/categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_category(category_id: int, db: DB, user: CurrentUser) -> None:
    cat = db.get(CompetitionCategory, category_id)
    if cat is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Category not found")
    require_manage_competition(db, user, cat.competition_id)
    if _active_teams(cat):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "This category still has teams — remove them first.",
        )
    db.delete(cat)
    db.commit()


@router.post("/categories/{category_id}/teams", status_code=status.HTTP_201_CREATED)
def add_team(category_id: int, payload: TeamCreate, db: DB, user: CurrentUser) -> TeamOut:
    cat = db.get(CompetitionCategory, category_id)
    if cat is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Category not found")
    require_manage_competition(db, user, cat.competition_id)
    comp = cat.competition
    team = CompetitionTeam(category_id=category_id, name=payload.name)
    db.add(team)
    db.flush()
    role_engine.apply_event(
        db, event="team_created", entity_type="team", entity_id=team.id,
        lineage=lineage_for_team(comp, team.id), names={"competition": comp.name, "team": team.name},
        creator_id=user.id, root_position_id=payload.role_root_position_id,
    )
    resync_managers(db)
    db.commit()
    db.refresh(team)
    return _team_out(db, comp, team, True, user)


@router.patch("/teams/{team_id}")
def edit_team(team_id: int, payload: TeamEdit, db: DB, user: CurrentUser) -> TeamOut:
    team = _get_team(db, team_id)
    comp = _team_competition(team)
    require_manage_competition(db, user, comp.id)
    if payload.name is not None and payload.name != team.name:
        team.name = payload.name
        names = {"competition": comp.name, "team": team.name}
        role_engine.retitle_positions_for_entity(db, "team", team.id, names)
        for member in team.members:
            role_engine.retitle_positions_for_entity(
                db, "membership", member.id, {**names, "member": member.user.full_name}
            )
    resync_managers(db)
    db.commit()
    db.refresh(team)
    return _team_out(db, comp, team, True, user)


@router.delete("/teams/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_team(team_id: int, db: DB, user: CurrentUser, permanent: bool = False) -> None:
    """Soft-deletes by default — a team is historical context (who competed,
    allocations, task history). `permanent=true` really removes it, admin
    only. Either way its role positions (and its members' role positions)
    follow: vacated on a soft delete (they stay in the org chart, same as the
    team staying queryable), removed outright on a permanent one."""
    team = _get_team(db, team_id)
    comp = _team_competition(team)
    require_manage_competition(db, user, comp.id)
    member_ids = [m.id for m in team.members]
    if permanent:
        if not user.is_admin:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "Only an admin can permanently delete a team"
            )
        audit_log(db, user.id, "competitions", "team_purged", "competition_team", team.id,
                  {"team": team.name})
        for mid in member_ids:
            role_engine.delete_positions_for_entity(db, "membership", mid)
        role_engine.delete_positions_for_entity(db, "team", team.id)
        db.delete(team)
    else:
        audit_log(db, user.id, "competitions", "team_deleted", "competition_team", team.id,
                  {"team": team.name})
        team.deleted_at = datetime.now(timezone.utc)
        for mid in member_ids:
            role_engine.vacate_positions_for_entity(db, "membership", mid)
        role_engine.vacate_positions_for_entity(db, "team", team.id)
    resync_managers(db)
    db.commit()


@router.post("/teams/{team_id}/members", status_code=status.HTTP_201_CREATED)
def add_member(team_id: int, payload: MemberAdd, db: DB, user: CurrentUser) -> TeamOut:
    team = _get_team(db, team_id)
    comp = _team_competition(team)
    require_manage_team(db, user, team)  # a scoped team manager qualifies here
    _resolve_user(db, payload.user_id, "Member")
    exists = db.scalar(
        select(CompetitionTeamMember).where(
            CompetitionTeamMember.team_id == team_id,
            CompetitionTeamMember.user_id == payload.user_id,
        )
    )
    if exists is None:
        member = CompetitionTeamMember(team_id=team_id, user_id=payload.user_id)
        db.add(member)
        db.flush()
        member_user = db.get(User, payload.user_id)
        role_engine.apply_event(
            db, event="team_member_added", entity_type="membership", entity_id=member.id,
            lineage=lineage_for_membership(comp, team.id, member.id),
            names={"competition": comp.name, "team": team.name, "member": member_user.full_name},
            member_id=payload.user_id, root_position_id=payload.role_root_position_id,
        )
        resync_managers(db)
        audit_log(db, user.id, "competitions", "member_added", "competition_team", team.id,
                  {"team": team.name, "user_id": payload.user_id})
        db.commit()
        db.refresh(team)
    return _team_out(db, comp, team, can_manage_team(db, user, team), user)


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
        role_engine.delete_positions_for_entity(db, "membership", member.id)
        db.delete(member)
        resync_managers(db)
        audit_log(db, user.id, "competitions", "member_removed", "competition_team", team.id,
                  {"team": team.name, "user_id": user_id})
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
    role_engine.apply_event(
        db, event="competition_created", entity_type="competition", entity_id=comp.id,
        lineage=lineage_for_competition(comp), names={"competition": comp.name},
        creator_id=user.id, root_position_id=payload.role_root_position_id,
    )
    resync_managers(db)
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
        role_engine.retitle_positions_for_entity(
            db, "competition", comp.id, {"competition": comp.name}
        )
        for cat in comp.categories:
            for team in cat.teams:
                names = {"competition": comp.name, "team": team.name}
                role_engine.retitle_positions_for_entity(db, "team", team.id, names)
                for member in team.members:
                    role_engine.retitle_positions_for_entity(
                        db, "membership", member.id, {**names, "member": member.user.full_name}
                    )
    if payload.description is not None:
        comp.description = payload.description
    status_changed = payload.status is not None and payload.status != comp.status
    if payload.status is not None:
        comp.status = payload.status
    comp.start_date = None if payload.clear_start_date else (payload.start_date or comp.start_date)
    comp.end_date = None if payload.clear_end_date else (payload.end_date or comp.end_date)
    if status_changed and comp.status == CompetitionStatus.ARCHIVED:
        # archiving vacates every seat this competition produced, at every
        # level — occupancy is manual now, so there is nothing to "restore"
        # on reactivation; reactivating just leaves seats vacant to refill.
        role_engine.vacate_positions_for_entity(db, "competition", comp.id)
        for cat in comp.categories:
            for team in cat.teams:
                role_engine.vacate_positions_for_entity(db, "team", team.id)
                for member in team.members:
                    role_engine.vacate_positions_for_entity(db, "membership", member.id)
        resync_managers(db)
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
    for cat in comp.categories:
        for team in cat.teams:
            for member in team.members:
                role_engine.delete_positions_for_entity(db, "membership", member.id)
            role_engine.delete_positions_for_entity(db, "team", team.id)
    role_engine.delete_positions_for_entity(db, "competition", comp.id)
    db.delete(comp)
    resync_managers(db)
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
