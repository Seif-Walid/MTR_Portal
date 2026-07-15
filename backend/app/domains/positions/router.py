from collections import defaultdict

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.domains.auth.deps import DB, CurrentUser
from app.domains.hierarchy.service import is_org_manager
from app.domains.positions.models import OrgAuditLog, Position
from app.domains.positions.schemas import PositionCreate, PositionEdit, PositionNode
from app.domains.positions.service import (
    assert_no_cycle,
    audit,
    clear_user_from_other_positions,
    resync_managers,
)
from app.domains.users.models import User
from app.domains.users.schemas import UserBrief

router = APIRouter(prefix="/org", tags=["organization"])


def _require_org_manager(user: User) -> None:
    if not is_org_manager(user):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Only the CEO or an admin can edit the org tree"
        )


def _resolve_occupant(db: DB, user_id: int | None) -> int | None:
    if user_id is None:
        return None
    if db.get(User, user_id) is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Occupant not found")
    return user_id


@router.get("/tree")
def org_tree(db: DB, user: CurrentUser) -> list[PositionNode]:
    """The whole position tree. Vacant seats included. Any signed-in user may view."""
    positions = list(db.scalars(select(Position)))
    children: dict[int | None, list[Position]] = defaultdict(list)
    for p in positions:
        children[p.parent_id].append(p)
    for group in children.values():
        group.sort(key=lambda p: p.title.lower())

    def build(p: Position) -> PositionNode:
        node = PositionNode.model_validate(p)
        node.children = [build(c) for c in children.get(p.id, [])]
        return node

    return [build(p) for p in children.get(None, [])]


@router.post("/positions", status_code=status.HTTP_201_CREATED)
def create_position(payload: PositionCreate, db: DB, user: CurrentUser) -> PositionNode:
    _require_org_manager(user)
    if payload.parent_id is None:
        if db.scalar(select(Position).where(Position.parent_id.is_(None))) is not None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "The org already has a root — add this under an existing position.",
            )
    elif db.get(Position, payload.parent_id) is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Parent position not found")

    occupant_id = _resolve_occupant(db, payload.occupant_id)
    position = Position(
        title=payload.title,
        parent_id=payload.parent_id,
        is_technical=payload.is_technical,
        occupant_id=occupant_id,
    )
    db.add(position)
    db.flush()
    if occupant_id is not None:
        clear_user_from_other_positions(db, occupant_id, keep_position_id=position.id)
    resync_managers(db)
    audit(db, user.id, "create", position.id,
          {"title": position.title, "parent_id": position.parent_id, "occupant_id": occupant_id})
    db.commit()
    db.refresh(position)
    return PositionNode.model_validate(position)


@router.patch("/positions/{position_id}")
def edit_position(position_id: int, payload: PositionEdit, db: DB, user: CurrentUser) -> PositionNode:
    _require_org_manager(user)
    position = db.get(Position, position_id)
    if position is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Position not found")

    if payload.title is not None:
        position.title = payload.title
    if payload.is_technical is not None:
        position.is_technical = payload.is_technical
    if payload.parent_id is not None and payload.parent_id != position.parent_id:
        if db.get(Position, payload.parent_id) is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Parent position not found")
        assert_no_cycle(db, position.id, payload.parent_id)
        position.parent_id = payload.parent_id
    if payload.clear_occupant:
        position.occupant_id = None
    elif payload.occupant_id is not None:
        position.occupant_id = _resolve_occupant(db, payload.occupant_id)
        clear_user_from_other_positions(db, position.occupant_id, keep_position_id=position.id)

    db.flush()
    resync_managers(db)
    audit(db, user.id, "edit", position.id,
          {"title": position.title, "parent_id": position.parent_id, "occupant_id": position.occupant_id})
    db.commit()
    db.refresh(position)
    return PositionNode.model_validate(position)


@router.delete("/positions/{position_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_position(position_id: int, db: DB, user: CurrentUser) -> None:
    _require_org_manager(user)
    position = db.get(Position, position_id)
    if position is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Position not found")
    if db.scalar(select(Position).where(Position.parent_id == position_id)) is not None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Reparent or remove the positions under this one first.",
        )
    # the former occupant is now unplaced
    if position.occupant_id is not None:
        occ = db.get(User, position.occupant_id)
        if occ is not None:
            occ.manager_id = None
    audit(db, user.id, "delete", position_id, {"title": position.title})
    db.delete(position)
    db.flush()
    resync_managers(db)
    db.commit()


@router.get("/audit")
def org_audit(db: DB, user: CurrentUser, limit: int = 50) -> list[dict]:
    _require_org_manager(user)
    rows = db.scalars(
        select(OrgAuditLog).order_by(OrgAuditLog.created_at.desc()).limit(min(limit, 200))
    )
    out = []
    for r in rows:
        actor = db.get(User, r.actor_id) if r.actor_id else None
        out.append({
            "id": r.id,
            "actor": actor.full_name if actor else "—",
            "action": r.action,
            "position_id": r.position_id,
            "detail": r.detail,
            "created_at": r.created_at.isoformat(),
        })
    return out
