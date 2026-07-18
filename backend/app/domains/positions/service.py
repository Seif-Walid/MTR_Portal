import json

from fastapi import HTTPException, status as http_status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domains.positions.models import OrgAuditLog, Position, PositionOccupant
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
    """Derive every occupant's users.manager_id from the position tree: they
    report to the earliest-added occupant of the nearest ancestor position
    that has one. Positions can have more than one occupant now (co-leads, a
    whole roster) — when a parent has several, the earliest-added one is
    treated as "the" manager for anyone below, same convention this app
    already used for "the" PM of a competition before that concept moved
    onto this same generic occupancy system.

    Role-template positions (role_template_id is not None — a competition's
    PM seat, a team's Lead/Coach/Member seat, whatever the admin has
    configured) are excluded entirely: holding one never sets your
    manager_id, and one is never treated as an ancestor's manager either.
    Those are an extra "hat" on top of someone's real place in the
    hierarchy, not a hierarchy position in their own right — see
    app/domains/positions/role_engine.py."""
    positions = all_positions(db)
    by_id = {p.id: p for p in positions}

    def earliest_occupant_id(pos: Position) -> int | None:
        return pos.occupant_links[0].user_id if pos.occupant_links else None

    def nearest_manager(pos: Position) -> int | None:
        seen: set[int] = set()
        cur = pos.parent_id
        while cur is not None and cur not in seen:
            seen.add(cur)
            parent = by_id.get(cur)
            if parent is None:
                break
            if parent.role_template_id is None:
                manager_id = earliest_occupant_id(parent)
                if manager_id is not None:
                    return manager_id
            cur = parent.parent_id
        return None

    for pos in positions:
        if pos.role_template_id is not None:
            continue
        if not pos.occupant_links:
            continue
        manager_id = nearest_manager(pos)
        for link in pos.occupant_links:
            occ = db.get(User, link.user_id)
            if occ is not None:
                occ.manager_id = manager_id


def clear_user_from_other_positions(db: Session, user_id: int, keep_position_id: int | None) -> None:
    """A person occupies at most one REAL seat. Role-template positions (see
    resync_managers above) are a separate kind of "hat" and are deliberately
    left alone — someone can hold their real seat and also occupy any number
    of role-template positions (a competition's PM, a team's Lead, a team's
    Coach, several at once) without being evicted from either."""
    for link in db.scalars(
        select(PositionOccupant)
        .join(Position, PositionOccupant.position_id == Position.id)
        .where(PositionOccupant.user_id == user_id, Position.role_template_id.is_(None))
    ):
        if link.position_id != keep_position_id:
            db.delete(link)


def audit(db: Session, actor_id: int, action: str, position_id: int | None, detail: dict) -> None:
    db.add(
        OrgAuditLog(
            actor_id=actor_id,
            action=action,
            position_id=position_id,
            detail=json.dumps(detail, default=str),
        )
    )
