from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.domains.access import service as access
from app.domains.auth.deps import DB, CurrentUser
from app.domains.inventory import stock
from app.domains.inventory.models import (
    InventoryItem,
    InventoryRequest,
    InventoryRequestStatus,
    Location,
)
from app.domains.inventory.schemas import (
    InventoryRequestCreate,
    InventoryRequestOut,
    RequestDecision,
    RequestIssue,
    RequestReturn,
)
from app.domains.inventory.service import get_item_or_404
from app.domains.notifications.models import NotificationType
from app.domains.notifications.service import notify
from app.domains.users.models import User

router = APIRouter(prefix="/inventory/requests", tags=["inventory-requests"])


def _get_request_or_404(db: DB, user, request_id: int) -> InventoryRequest:
    req = db.get(InventoryRequest, request_id)
    if req is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Request not found")
    # visible to the requester, or to anyone who approves stock movement
    if req.requester_id != user.id and not access.has_privilege(db, user, "inventory.approve"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Request not found")
    return req


@router.get("")
def list_requests(
    db: DB, user: CurrentUser, view: str = "mine", status_filter: str | None = None
) -> list[InventoryRequestOut]:
    """view=mine (default): my own requests. view=to_review: submitted requests
    a manager can act on (staff only). view=all: staff see every request."""
    query = select(InventoryRequest)
    if view == "to_review":
        access.require_privilege(db, user, "inventory.approve")
        query = query.where(InventoryRequest.status == InventoryRequestStatus.SUBMITTED)
    elif view == "all" and access.has_privilege(db, user, "inventory.approve"):
        pass  # no filter — staff see everything
    else:
        query = query.where(InventoryRequest.requester_id == user.id)
    if status_filter:
        query = query.where(InventoryRequest.status == status_filter)
    rows = db.scalars(query.order_by(InventoryRequest.created_at.desc()))
    return [InventoryRequestOut.model_validate(r) for r in rows]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_request(payload: InventoryRequestCreate, db: DB, user: CurrentUser) -> InventoryRequestOut:
    access.require_privilege(db, user, "inventory.request")
    item = get_item_or_404(db, user, payload.item_id)  # must be visible to the requester
    req = InventoryRequest(
        item_id=item.id,
        requester_id=user.id,
        quantity=payload.quantity,
        reason=payload.reason,
        needed_by=payload.needed_by,
        return_by=payload.return_by,
    )
    db.add(req)
    db.flush()
    if item.team_lead_id and item.team_lead_id != user.id:
        notify(
            db, item.team_lead_id, NotificationType.REQUEST_RECEIVED,
            f"{user.full_name} requested {payload.quantity} {item.unit}(s) of '{item.name}'",
        )
    db.commit()
    db.refresh(req)
    return InventoryRequestOut.model_validate(req)


@router.post("/{request_id}/approve")
def approve_request(request_id: int, db: DB, user: CurrentUser) -> InventoryRequestOut:
    access.require_privilege(db, user, "inventory.approve")
    req = _get_request_or_404(db, user, request_id)
    if req.status != InventoryRequestStatus.SUBMITTED:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Only a submitted request can be approved")
    req.status = InventoryRequestStatus.APPROVED
    req.approver_id = user.id
    notify(db, req.requester_id, NotificationType.REQUEST_ACCEPTED,
           f"Your request for '{req.item.name}' was approved")
    db.commit()
    db.refresh(req)
    return InventoryRequestOut.model_validate(req)


@router.post("/{request_id}/reject")
def reject_request(request_id: int, payload: RequestDecision, db: DB, user: CurrentUser) -> InventoryRequestOut:
    access.require_privilege(db, user, "inventory.approve")
    req = _get_request_or_404(db, user, request_id)
    if req.status != InventoryRequestStatus.SUBMITTED:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Only a submitted request can be rejected")
    req.status = InventoryRequestStatus.REJECTED
    req.approver_id = user.id
    req.decision_reason = payload.reason
    notify(db, req.requester_id, NotificationType.REQUEST_DECLINED,
           f"Your request for '{req.item.name}' was rejected"
           + (f": {payload.reason}" if payload.reason else ""))
    db.commit()
    db.refresh(req)
    return InventoryRequestOut.model_validate(req)


@router.post("/{request_id}/issue")
def issue_request(request_id: int, payload: RequestIssue, db: DB, user: CurrentUser) -> InventoryRequestOut:
    """Issuing is the ONLY way an approved request creates stock movement —
    moves `quantity` from the chosen location to the requester."""
    access.require_privilege(db, user, "inventory.approve")
    req = _get_request_or_404(db, user, request_id)
    if req.status != InventoryRequestStatus.APPROVED:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Only an approved request can be issued")
    if db.get(Location, payload.from_location_id) is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Location not found")
    item = db.get(InventoryItem, req.item_id)
    stock.record_movement(
        db, item, req.quantity,
        from_location_id=payload.from_location_id, from_holder_id=None,
        to_location_id=None, to_holder_id=req.requester_id,
        actor_id=user.id, reason=f"Issued via request #{req.id}", request_id=req.id,
    )
    req.status = InventoryRequestStatus.ISSUED
    req.issued_at = datetime.now(timezone.utc)
    notify(db, req.requester_id, NotificationType.REQUEST_ACCEPTED,
           f"'{item.name}' x{req.quantity} has been issued to you")
    db.commit()
    db.refresh(req)
    return InventoryRequestOut.model_validate(req)


@router.post("/{request_id}/return")
def return_request(request_id: int, payload: RequestReturn, db: DB, user: CurrentUser) -> InventoryRequestOut:
    """The requester or an inventory manager may check the units back in."""
    req = _get_request_or_404(db, user, request_id)
    if req.requester_id != user.id and not access.has_privilege(db, user, "inventory.approve"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the requester or an inventory manager can return this")
    if req.status != InventoryRequestStatus.ISSUED:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Only an issued request can be returned")
    if db.get(Location, payload.to_location_id) is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Location not found")
    item = db.get(InventoryItem, req.item_id)
    stock.record_movement(
        db, item, req.quantity,
        from_location_id=None, from_holder_id=req.requester_id,
        to_location_id=payload.to_location_id, to_holder_id=None,
        actor_id=user.id, reason=f"Returned via request #{req.id}", request_id=req.id,
    )
    req.status = InventoryRequestStatus.RETURNED
    req.returned_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(req)
    return InventoryRequestOut.model_validate(req)
