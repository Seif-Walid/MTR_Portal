"""Stock whereabouts, derived from the append-only StockMovement ledger.

On-hand is never stored — it is summed from movements, so it always reconciles
against the ledger. A movement carries `quantity` from a source (a location, a
holder, or nowhere = stock-in) to a destination (a location, a holder, or
nowhere = stock-out / consumed).
"""

from collections import defaultdict

from fastapi import HTTPException, status as http_status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domains.inventory.models import InventoryItem, StockMovement


def whereabouts(db: Session, item_id: int) -> tuple[dict[int, int], dict[int, int], int]:
    """Return (on-hand by location_id, on-hand by holder_id, total tracked)."""
    by_location: dict[int, int] = defaultdict(int)
    by_holder: dict[int, int] = defaultdict(int)
    total = 0
    for m in db.scalars(select(StockMovement).where(StockMovement.item_id == item_id)):
        if m.from_location_id is not None:
            by_location[m.from_location_id] -= m.quantity
        elif m.from_holder_id is not None:
            by_holder[m.from_holder_id] -= m.quantity
        else:
            total += m.quantity  # stock-in from nowhere
        if m.to_location_id is not None:
            by_location[m.to_location_id] += m.quantity
        elif m.to_holder_id is not None:
            by_holder[m.to_holder_id] += m.quantity
        else:
            total -= m.quantity  # stock-out to nowhere
    return (
        {k: v for k, v in by_location.items() if v},
        {k: v for k, v in by_holder.items() if v},
        total,
    )


def place_on_hand(db: Session, item_id: int, location_id: int | None, holder_id: int | None) -> int:
    by_location, by_holder, _ = whereabouts(db, item_id)
    if location_id is not None:
        return by_location.get(location_id, 0)
    if holder_id is not None:
        return by_holder.get(holder_id, 0)
    return 0  # "nowhere" is unbounded (stock-in source)


def record_movement(
    db: Session,
    item: InventoryItem,
    quantity: int,
    *,
    from_location_id: int | None,
    from_holder_id: int | None,
    to_location_id: int | None,
    to_holder_id: int | None,
    actor_id: int,
    reason: str,
    request_id: int | None = None,
) -> StockMovement:
    if quantity <= 0:
        raise HTTPException(http_status.HTTP_400_BAD_REQUEST, "Quantity must be positive")
    if from_location_id is not None and from_holder_id is not None:
        raise HTTPException(http_status.HTTP_400_BAD_REQUEST, "A move has one source")
    if to_location_id is not None and to_holder_id is not None:
        raise HTTPException(http_status.HTTP_400_BAD_REQUEST, "A move has one destination")
    # guard against moving more than is on hand at a real source
    if from_location_id is not None or from_holder_id is not None:
        available = place_on_hand(db, item.id, from_location_id, from_holder_id)
        if quantity > available:
            raise HTTPException(
                http_status.HTTP_400_BAD_REQUEST,
                f"Only {available} {item.unit}(s) on hand at the source.",
            )
    movement = StockMovement(
        item_id=item.id,
        quantity=quantity,
        from_location_id=from_location_id,
        from_holder_id=from_holder_id,
        to_location_id=to_location_id,
        to_holder_id=to_holder_id,
        actor_id=actor_id,
        reason=reason,
        request_id=request_id,
    )
    db.add(movement)
    return movement
