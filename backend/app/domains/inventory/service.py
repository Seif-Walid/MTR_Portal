from fastapi import HTTPException, status as http_status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domains.access import service as access
from app.domains.inventory.models import InventoryAllocation, InventoryItem
from app.domains.users.models import User


def can_manage_inventory(db: Session, user: User) -> bool:
    """inventory.edit: create, edit, delete, allocate, import, sync."""
    return access.has_privilege(db, user, "inventory.edit")


def can_view_inventory(db: Session, user: User) -> bool:
    """Who may list/read the storage. `inventory.view` is the explicit grant, but
    anyone who can edit or move stock necessarily sees it too — you can't manage
    what you can't list, and every preset level bundles view with those. Guards
    against an access level that got edit but not view."""
    return any(
        access.has_privilege(db, user, key)
        for key in ("inventory.view", "inventory.edit", "inventory.approve")
    )


def visible_items_query(db: Session, user: User):
    """Viewers see the full storage; anyone without view access sees nothing.
    Soft-deleted items never appear through the normal API."""
    base = select(InventoryItem).where(InventoryItem.deleted_at.is_(None))
    if can_view_inventory(db, user):
        return base
    return base.where(InventoryItem.id.is_(None))


def can_view_item(db: Session, user: User, item: InventoryItem) -> bool:
    if item.deleted_at is not None:
        return False
    return can_view_inventory(db, user)


def get_item_or_404(db: Session, user: User, item_id: int) -> InventoryItem:
    item = db.get(InventoryItem, item_id)
    if item is None or not can_view_item(db, user, item):
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, "Item not found")
    return item


def require_manage(db: Session, user: User) -> None:
    access.require_privilege(db, user, "inventory.edit")


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
