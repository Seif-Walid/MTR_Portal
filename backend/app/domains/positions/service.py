import json

from fastapi import HTTPException, status as http_status
from sqlalchemy import select, update
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
    already used for "the" PM of a event before that concept moved
    onto this same generic occupancy system.

    Role-template positions (role_template_id is not None — a event's
    PM seat, a team's Lead/Coach/Member seat, whatever the admin has
    configured) are excluded entirely: holding one never sets your
    manager_id, and one is never treated as an ancestor's manager either.
    Those are an extra "hat" on top of someone's real place in the
    hierarchy, not a hierarchy position in their own right — see
    app/domains/positions/role_engine.py."""
    # Clear the slate for position-derived reporting lines before re-deriving,
    # so that removing someone's real seat actually detaches them (the loop
    # below only ever *sets* manager_id for current real occupants, never
    # clears a stale one). A position-derived manager_id always points at the
    # earliest occupant of a *real* ancestor position, so reset exactly the
    # rows whose manager is such an occupant. Reporting lines seeded/imported
    # without any position point at a non-occupant and are deliberately left
    # untouched.
    real_occupant_ids = (
        select(PositionOccupant.user_id)
        .join(Position, PositionOccupant.position_id == Position.id)
        .where(Position.role_template_id.is_(None))
    )
    db.execute(
        update(User)
        .where(User.manager_id.in_(real_occupant_ids))
        .values(manager_id=None)
        # "fetch" keeps already-loaded User rows in step, so re-setting the
        # same manager below is seen as a change and actually written back
        .execution_options(synchronize_session="fetch")
    )

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

    # A person can hold several real seats (Instructor and Software Lead, say).
    # manager_id is a single reporting line, so it comes from the highest of
    # their seats (fewest ancestors) — a seat below one of their own never
    # makes them their own manager. Tasking reaches every seat's subtree
    # regardless (hierarchy.position_subordinate_ids).
    def depth(pos: Position) -> int:
        d, cur, seen = 0, pos.parent_id, set()
        while cur is not None and cur not in seen:
            seen.add(cur)
            d += 1
            cur = by_id[cur].parent_id if cur in by_id else None
        return d

    assigned: set[int] = set()
    for pos in sorted(positions, key=lambda p: (depth(p), p.id)):
        if pos.role_template_id is not None:
            continue
        if not pos.occupant_links:
            continue
        manager_id = nearest_manager(pos)
        for link in pos.occupant_links:
            if link.user_id in assigned:
                continue
            assigned.add(link.user_id)
            occ = db.get(User, link.user_id)
            if occ is not None:
                occ.manager_id = manager_id if manager_id != occ.id else None


def audit(db: Session, actor_id: int, action: str, position_id: int | None, detail: dict) -> None:
    db.add(
        OrgAuditLog(
            actor_id=actor_id,
            action=action,
            position_id=position_id,
            detail=json.dumps(detail, default=str),
        )
    )
