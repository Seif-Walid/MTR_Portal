from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.domains.access import service as access
from app.domains.auth.deps import DB, CurrentUser
from app.domains.timeblocks import service
from app.domains.timeblocks.models import TimeBlock
from app.domains.timeblocks.schemas import (
    TimeBlockCreate,
    TimeBlockEdit,
    TimeBlockOut,
)

router = APIRouter(prefix="/timeblocks", tags=["timeblocks"])


@router.get("")
def list_blocks(
    db: DB,
    user: CurrentUser,
    team_type: str,
    event_team_id: int | None = None,
    position_id: int | None = None,
) -> list[TimeBlockOut]:
    """Time blocks for one team. `team_type` is 'event' (with event_team_id) or
    'org' (with position_id)."""
    if team_type == "event":
        access.require_privilege(db, user, "events.view")
        if event_team_id is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "event_team_id required.")
        q = select(TimeBlock).where(
            TimeBlock.team_type == "event",
            TimeBlock.event_team_id == event_team_id,
        )
    elif team_type == "org":
        access.require_privilege(db, user, "people.view")
        if position_id is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "position_id required.")
        q = select(TimeBlock).where(
            TimeBlock.team_type == "org",
            TimeBlock.position_id == position_id,
        )
    else:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid team_type.")
    q = q.order_by(TimeBlock.start_date)
    return [TimeBlockOut.model_validate(b) for b in db.scalars(q)]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_block(body: TimeBlockCreate, db: DB, user: CurrentUser) -> TimeBlockOut:
    if body.end_date < body.start_date:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "End date is before start.")
    service.require_manage_target(
        db, user, body.team_type, body.event_team_id, body.position_id
    )
    if body.team_type == "event":
        service.require_within_event(
            db, body.event_team_id, body.start_date, body.end_date
        )
    block = TimeBlock(
        team_type=body.team_type,
        event_team_id=body.event_team_id if body.team_type == "event" else None,
        position_id=body.position_id if body.team_type == "org" else None,
        title=body.title.strip(),
        start_date=body.start_date,
        end_date=body.end_date,
        weekday_mask=body.weekday_mask,
        created_by=user.id,
    )
    db.add(block)
    db.commit()
    db.refresh(block)
    return TimeBlockOut.model_validate(block)


@router.patch("/{block_id}")
def edit_block(
    block_id: int, body: TimeBlockEdit, db: DB, user: CurrentUser
) -> TimeBlockOut:
    block = db.get(TimeBlock, block_id)
    if block is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Block not found.")
    service.require_manage_target(
        db, user, block.team_type, block.event_team_id, block.position_id
    )
    if body.title is not None:
        block.title = body.title.strip()
    if body.start_date is not None:
        block.start_date = body.start_date
    if body.end_date is not None:
        block.end_date = body.end_date
    if body.weekday_mask is not None:
        block.weekday_mask = body.weekday_mask
    if block.end_date < block.start_date:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "End date is before start.")
    if block.team_type == "event":
        service.require_within_event(
            db, block.event_team_id, block.start_date, block.end_date
        )
    db.commit()
    db.refresh(block)
    return TimeBlockOut.model_validate(block)


@router.delete("/{block_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_block(block_id: int, db: DB, user: CurrentUser) -> None:
    block = db.get(TimeBlock, block_id)
    if block is None:
        return
    service.require_manage_target(
        db, user, block.team_type, block.event_team_id, block.position_id
    )
    db.delete(block)
    db.commit()
