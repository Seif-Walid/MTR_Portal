"""Business logic for team time blocks: how a block expands onto the calendar,
who may create one, and how the two team flavours (event team / org unit)
resolve to a name, a membership test, and a manage gate.
"""

from datetime import date, timedelta

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domains.access import service as access
from app.domains.events.models import EventTeam
from app.domains.events.service import require_manage_team
from app.domains.positions.models import Position, PositionOccupant
from app.domains.positions.service import descendant_ids
from app.domains.timeblocks.models import TimeBlock
from app.domains.users.models import User


def expand_block(
    block: TimeBlock, start: date | None, end: date | None
) -> list[tuple[date, date | None]]:
    """Turn a block into concrete calendar marks, clamped to [start, end].

    A whole-span block (weekday_mask == 0) yields one (start, end) range; a
    recurring block yields one single-day mark per matching weekday. Returns
    (day, None) for single-day marks and (from, to) for the span."""
    s = block.start_date
    e = block.end_date
    if start is not None and s < start:
        s = start
    if end is not None and e > end:
        e = end
    if s > e:
        return []
    if block.weekday_mask == 0:
        return [(s, e)]
    out: list[tuple[date, date | None]] = []
    d = s
    while d <= e:
        if block.weekday_mask & (1 << d.weekday()):
            out.append((d, None))
        d += timedelta(days=1)
    return out


def _occupied_position_ids(db: Session, user_id: int) -> set[int]:
    return set(
        db.scalars(
            select(PositionOccupant.position_id).where(
                PositionOccupant.user_id == user_id
            )
        )
    )


def org_root_position(db: Session, user: User) -> tuple[int | None, bool]:
    """The org unit this user's "My Team" block schedules, and whether they may.

    Returns (position_id, can_schedule). A user who leads a real position (one
    with children) schedules that unit. A pure member schedules nothing unless
    they hold org.edit, in which case they schedule their own unit (their seat's
    parent)."""
    reals = db.scalars(
        select(Position)
        .join(PositionOccupant, PositionOccupant.position_id == Position.id)
        .where(
            PositionOccupant.user_id == user.id,
            Position.role_template_id.is_(None),
        )
    ).all()
    if not reals:
        return None, False

    def has_children(pid: int) -> bool:
        return (
            db.scalar(select(Position.id).where(Position.parent_id == pid).limit(1))
            is not None
        )

    leads = [p for p in reals if has_children(p.id)]
    if leads:
        return min(leads, key=lambda p: p.id).id, True

    can_edit = access.has_privilege(db, user, "org.edit")
    with_parent = [p for p in reals if p.parent_id is not None]
    if with_parent:
        return min(with_parent, key=lambda p: p.id).parent_id, can_edit
    return None, can_edit


def can_manage_position(db: Session, user: User, position_id: int) -> bool:
    """True if the user leads this org unit — occupies it or any ancestor — or
    holds the global org.edit privilege."""
    if access.has_privilege(db, user, "org.edit"):
        return True
    occupied = _occupied_position_ids(db, user.id)
    cur: int | None = position_id
    seen: set[int] = set()
    while cur is not None and cur not in seen:
        if cur in occupied:
            return True
        seen.add(cur)
        cur = db.scalar(select(Position.parent_id).where(Position.id == cur))
    return False


def user_in_org_position(db: Session, user_id: int, position_id: int) -> bool:
    """True if the user occupies this org unit or any position beneath it."""
    ids = {position_id} | descendant_ids(db, position_id)
    return (
        db.scalar(
            select(PositionOccupant.id)
            .where(
                PositionOccupant.position_id.in_(ids),
                PositionOccupant.user_id == user_id,
            )
            .limit(1)
        )
        is not None
    )


def require_manage_target(
    db: Session,
    user: User,
    team_type: str,
    event_team_id: int | None,
    position_id: int | None,
) -> None:
    """Gate for creating/editing a block: event-team blocks reuse the event
    domain's manage-team check (which already lets event managers through); org
    blocks require leading that org unit."""
    if team_type == "event":
        team = db.get(EventTeam, event_team_id) if event_team_id else None
        if team is None or team.deleted_at is not None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Team not found.")
        require_manage_team(db, user, team)
    elif team_type == "org":
        if position_id is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "position_id required.")
        if not can_manage_position(db, user, position_id):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Only this org unit's lead can schedule its time.",
            )
    else:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid team_type.")


def require_within_event(
    db: Session, event_team_id: int | None, start: date, end: date
) -> None:
    """An event team's time can't spill outside its event's own span. Only the
    bounds the event actually has are enforced (a dateless edge stays open).
    Org units have no event and no bound — never call this for them."""
    team = db.get(EventTeam, event_team_id) if event_team_id else None
    event = team.category.event if team and team.category else None
    if event is None:
        return
    if event.start_date is not None and start < event.start_date:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Time can't start before the event ({event.start_date}).",
        )
    if event.end_date is not None and end > event.end_date:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Time can't run past the event ({event.end_date}).",
        )


def block_display(db: Session, block: TimeBlock) -> tuple[str, str | None]:
    """(title, detail) for a calendar mark. title falls back to the team name;
    detail is the event name (event teams) or 'Org' (org units)."""
    if block.team_type == "event":
        team = db.get(EventTeam, block.event_team_id) if block.event_team_id else None
        name = team.name if team else "Team"
        event_name = None
        if team and team.category and team.category.event:
            event_name = team.category.event.name
        return (block.title or name), event_name
    pos = db.get(Position, block.position_id) if block.position_id else None
    unit = pos.title if pos else "Org unit"
    return (block.title or unit), "Org"
