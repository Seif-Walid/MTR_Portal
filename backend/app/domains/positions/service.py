import json

from fastapi import HTTPException, status as http_status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domains.positions.models import OrgAuditLog, Position
from app.domains.users.models import User


def all_positions(db: Session) -> list[Position]:
    return list(db.scalars(select(Position)))


def descendant_ids(db: Session, position_id: int) -> set[int]:
    """IDs strictly below a position, via a recursive CTE."""
    base = select(Position.id).where(Position.parent_id == position_id)
    tree = base.cte(name="pos_subtree", recursive=True)
    tree = tree.union_all(select(Position.id).where(Position.parent_id == tree.c.id))
    return set(db.scalars(select(tree.c.id)))


def assert_no_cycle(db: Session, position_id: int, new_parent_id: int | None) -> None:
    if new_parent_id is None:
        return
    if new_parent_id == position_id or new_parent_id in descendant_ids(db, position_id):
        raise HTTPException(
            http_status.HTTP_400_BAD_REQUEST,
            "That move would create a cycle in the org tree.",
        )


def resync_managers(db: Session) -> None:
    """Derive each occupant's users.manager_id from the position tree: they report
    to the occupant of the nearest ancestor position that has one. This keeps the
    existing permission engine (which runs on manager_id) in sync with positions."""
    positions = all_positions(db)
    by_id = {p.id: p for p in positions}

    def nearest_manager(pos: Position) -> int | None:
        seen: set[int] = set()
        cur = pos.parent_id
        while cur is not None and cur not in seen:
            seen.add(cur)
            parent = by_id.get(cur)
            if parent is None:
                break
            if parent.occupant_id is not None:
                return parent.occupant_id
            cur = parent.parent_id
        return None

    for pos in positions:
        if pos.occupant_id is None:
            continue
        occ = db.get(User, pos.occupant_id)
        if occ is not None:
            occ.manager_id = nearest_manager(pos)


def clear_user_from_other_positions(db: Session, user_id: int, keep_position_id: int | None) -> None:
    """A person occupies at most one seat."""
    for pos in db.scalars(select(Position).where(Position.occupant_id == user_id)):
        if pos.id != keep_position_id:
            pos.occupant_id = None


def audit(db: Session, actor_id: int, action: str, position_id: int | None, detail: dict) -> None:
    db.add(
        OrgAuditLog(
            actor_id=actor_id,
            action=action,
            position_id=position_id,
            detail=json.dumps(detail, default=str),
        )
    )
