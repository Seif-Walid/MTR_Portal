from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select

from app.domains.auth.deps import DB, CurrentUser
from app.domains.competitions.models import (
    Competition,
    CompetitionCategory,
    CompetitionMember,
    CompetitionStatus,
)
from app.domains.competitions.schemas import (
    CategoryCreate,
    CategoryOut,
    CompetitionCreate,
    CompetitionDetailOut,
    CompetitionEdit,
    CompetitionOut,
    MemberAdd,
)
from app.domains.inventory.models import InventoryAllocation
from app.domains.users.models import User

router = APIRouter(prefix="/competitions", tags=["competitions"])


def _require_manage(user: User) -> None:
    """Competitions are edited by high staff (leadership tier) and the admin."""
    if not user.is_high_staff:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only senior staff can manage competitions")


def _resolve_user(db: DB, user_id: int | None, what: str) -> int | None:
    if user_id is None:
        return None
    if db.get(User, user_id) is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{what} not found")
    return user_id


def _resolve_category(db: DB, category_id: int | None) -> int | None:
    if category_id is None:
        return None
    if db.get(CompetitionCategory, category_id) is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Category not found")
    return category_id


def _out(db: DB, comp: Competition) -> CompetitionOut:
    out = CompetitionOut.model_validate(comp)
    out.member_count = len(comp.members)
    out.allocation_count = db.scalar(
        select(func.count())
        .select_from(InventoryAllocation)
        .where(InventoryAllocation.competition_id == comp.id)
    ) or 0
    return out


# --- categories (literal routes — before /{competition_id}) ---------------
@router.get("/categories")
def list_categories(db: DB, user: CurrentUser) -> list[CategoryOut]:
    cats = db.scalars(select(CompetitionCategory).order_by(CompetitionCategory.name)).all()
    return [CategoryOut.model_validate(c) for c in cats]


@router.post("/categories", status_code=status.HTTP_201_CREATED)
def create_category(payload: CategoryCreate, db: DB, user: CurrentUser) -> CategoryOut:
    _require_manage(user)
    if db.scalar(select(CompetitionCategory).where(CompetitionCategory.name == payload.name)):
        raise HTTPException(status.HTTP_409_CONFLICT, "That category already exists")
    cat = CompetitionCategory(name=payload.name)
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return CategoryOut.model_validate(cat)


@router.delete("/categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_category(category_id: int, db: DB, user: CurrentUser) -> None:
    _require_manage(user)
    cat = db.get(CompetitionCategory, category_id)
    if cat is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Category not found")
    db.delete(cat)  # competitions keep going (FK SET NULL)
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
    return [_out(db, c) for c in comps]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_competition(payload: CompetitionCreate, db: DB, user: CurrentUser) -> CompetitionOut:
    _require_manage(user)
    if db.scalar(select(Competition).where(Competition.name == payload.name)):
        raise HTTPException(status.HTTP_409_CONFLICT, "A competition with that name already exists")
    comp = Competition(
        name=payload.name,
        category_id=_resolve_category(db, payload.category_id),
        start_date=payload.start_date,
        end_date=payload.end_date,
        team_name=payload.team_name,
        team_lead_id=_resolve_user(db, payload.team_lead_id, "Team lead"),
        notes=payload.notes,
    )
    db.add(comp)
    db.commit()
    db.refresh(comp)
    return _out(db, comp)


@router.get("/{competition_id}")
def get_competition(competition_id: int, db: DB, user: CurrentUser) -> CompetitionDetailOut:
    comp = db.get(Competition, competition_id)
    if comp is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Competition not found")
    out = CompetitionDetailOut.model_validate(comp)
    out.member_count = len(comp.members)
    out.allocation_count = db.scalar(
        select(func.count())
        .select_from(InventoryAllocation)
        .where(InventoryAllocation.competition_id == comp.id)
    ) or 0
    return out


@router.patch("/{competition_id}")
def edit_competition(
    competition_id: int, payload: CompetitionEdit, db: DB, user: CurrentUser
) -> CompetitionOut:
    _require_manage(user)
    comp = db.get(Competition, competition_id)
    if comp is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Competition not found")
    if payload.name is not None and payload.name != comp.name:
        if db.scalar(select(Competition).where(Competition.name == payload.name)):
            raise HTTPException(status.HTTP_409_CONFLICT, "A competition with that name already exists")
        comp.name = payload.name
    for field in ("status", "notes", "team_name"):
        value = getattr(payload, field)
        if value is not None:
            setattr(comp, field, value)
    if payload.clear_category:
        comp.category_id = None
    elif payload.category_id is not None:
        comp.category_id = _resolve_category(db, payload.category_id)
    if payload.clear_team_lead:
        comp.team_lead_id = None
    elif payload.team_lead_id is not None:
        comp.team_lead_id = _resolve_user(db, payload.team_lead_id, "Team lead")
    comp.start_date = None if payload.clear_start_date else (payload.start_date or comp.start_date)
    comp.end_date = None if payload.clear_end_date else (payload.end_date or comp.end_date)
    db.commit()
    db.refresh(comp)
    return _out(db, comp)


@router.delete("/{competition_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_competition(competition_id: int, db: DB, user: CurrentUser) -> None:
    _require_manage(user)
    comp = db.get(Competition, competition_id)
    if comp is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Competition not found")
    in_use = db.scalar(
        select(func.count())
        .select_from(InventoryAllocation)
        .where(InventoryAllocation.competition_id == competition_id)
    )
    if in_use:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"{in_use} allocation(s) reference this competition — archive it instead.",
        )
    db.delete(comp)  # members cascade
    db.commit()


# --- members --------------------------------------------------------------
@router.post("/{competition_id}/members", status_code=status.HTTP_201_CREATED)
def add_member(competition_id: int, payload: MemberAdd, db: DB, user: CurrentUser) -> CompetitionDetailOut:
    _require_manage(user)
    comp = db.get(Competition, competition_id)
    if comp is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Competition not found")
    _resolve_user(db, payload.user_id, "Member")
    exists = db.scalar(
        select(CompetitionMember).where(
            CompetitionMember.competition_id == competition_id,
            CompetitionMember.user_id == payload.user_id,
        )
    )
    if exists is None:
        db.add(CompetitionMember(competition_id=competition_id, user_id=payload.user_id))
        db.commit()
        db.refresh(comp)
    return get_competition(competition_id, db, user)


@router.delete("/{competition_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(competition_id: int, user_id: int, db: DB, user: CurrentUser) -> None:
    _require_manage(user)
    member = db.scalar(
        select(CompetitionMember).where(
            CompetitionMember.competition_id == competition_id,
            CompetitionMember.user_id == user_id,
        )
    )
    if member is not None:
        db.delete(member)
        db.commit()
