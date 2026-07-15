from fastapi import HTTPException, status as http_status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domains.hierarchy.service import ancestor_ids
from app.domains.inventory.models import InventoryAllocation, InventoryItem
from app.domains.users.models import User


def can_manage_inventory(user: User) -> bool:
    """Staff (and the technical admin) get full storage: create, edit, delete,
    allocate, and sync. Non-staff members are read-only."""
    return user.is_staff or user.is_admin


def visible_items_query(db: Session, user: User):
    """Staff see the full storage; non-staff see only equipment designated to a
    team lead on their manager chain (their dedicated stuff). Soft-deleted
    items never appear through the normal API."""
    base = select(InventoryItem).where(InventoryItem.deleted_at.is_(None))
    if can_manage_inventory(user):
        return base
    teams = ancestor_ids(db, user.id, include_self=True)
    if not teams:
        # no team → nothing designated to them
        return base.where(InventoryItem.id.is_(None))
    return base.where(InventoryItem.team_lead_id.in_(teams))


def can_view_item(db: Session, user: User, item: InventoryItem) -> bool:
    if item.deleted_at is not None:
        return False
    if can_manage_inventory(user):
        return True
    if item.team_lead_id is None:
        return False
    return item.team_lead_id in ancestor_ids(db, user.id, include_self=True)


def get_item_or_404(db: Session, user: User, item_id: int) -> InventoryItem:
    item = db.get(InventoryItem, item_id)
    if item is None or not can_view_item(db, user, item):
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, "Item not found")
    return item


def require_manage(user: User) -> None:
    if not can_manage_inventory(user):
        raise HTTPException(
            http_status.HTTP_403_FORBIDDEN, "Only staff can manage inventory"
        )


def get_allocation_or_404(
    db: Session, user: User, allocation_id: int
) -> InventoryAllocation:
    allocation = db.get(InventoryAllocation, allocation_id)
    if allocation is None:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, "Allocation not found")
    get_item_or_404(db, user, allocation.item_id)  # visibility check on parent
    return allocation


def allocated_excluding(item: InventoryItem, exclude_id: int | None = None) -> int:
    """Units already allocated on this item, optionally excluding one allocation
    (used when editing that allocation in place)."""
    return sum(a.quantity for a in item.allocations if a.id != exclude_id)


def assert_fits(item: InventoryItem, want: int, exclude_id: int | None = None) -> None:
    """Guard: allocations must never exceed the total pool."""
    already = allocated_excluding(item, exclude_id)
    if already + want > item.quantity:
        free = item.quantity - already
        raise HTTPException(
            http_status.HTTP_400_BAD_REQUEST,
            f"Only {free} {item.unit}(s) free — cannot allocate {want}.",
        )


def assert_quantity_covers_allocations(item: InventoryItem, new_quantity: int) -> None:
    """Guard: shrinking the pool below what's already checked out is rejected."""
    if new_quantity < item.in_use:
        raise HTTPException(
            http_status.HTTP_400_BAD_REQUEST,
            f"{item.in_use} {item.unit}(s) are in use — cannot set the total below that.",
        )
