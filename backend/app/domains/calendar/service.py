"""Calendar aggregation: gathers dated things from across the app into one
list of CalendarItems. Two scopes — "me" (only what you participate in) and
"general" (everything you're permitted to see, respecting the same view
privileges as the rest of the app). Each source is independent: a source the
caller can't view is silently skipped, and the frontend picks which sources
to request.
"""

from datetime import date

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.domains.access import service as access
from app.domains.calendar.schemas import CalendarItem
from app.domains.events.models import (
    Event,
    EventStatus,
    EventTeam,
    EventTeamMember,
)
from app.domains.hierarchy.service import visible_user_ids
from app.domains.inventory.models import InventoryRequest, InventoryRequestStatus
from app.domains.positions.models import Position, PositionOccupant
from app.domains.requests.models import WorkRequest
from app.domains.tasks.models import Task
from app.domains.tasks.service import visible_tasks_query
from app.domains.users.models import User

SOURCES = ("tasks", "events", "inventory", "requests")


def _in_window(d: date | None, start: date | None, end: date | None) -> bool:
    if d is None:
        return False
    if start is not None and d < start:
        return False
    if end is not None and d > end:
        return False
    return True


def _tasks(db: Session, user: User, scope: str, start, end) -> list[CalendarItem]:
    if not access.has_privilege(db, user, "tasks.use"):
        return []
    if scope == "me":
        query = select(Task).where(
            or_(Task.assignee_id == user.id, Task.assigner_id == user.id)
        )
    else:
        query = visible_tasks_query(db, user)
    query = query.where(Task.due_date.is_not(None))
    if start is not None:
        query = query.where(Task.due_date >= start)
    if end is not None:
        query = query.where(Task.due_date <= end)
    out = []
    for t in db.scalars(query).unique():
        out.append(CalendarItem(
            source="task", id=t.id, title=t.title, start=t.due_date,
            kind=t.status,
            overdue=t.due_date < date.today() and t.status not in ("approved",),
        ))
    return out


def _my_event_ids(db: Session, user: User) -> set[int]:
    """Events the user participates in: as a team member, or by
    occupying any role seat for the event / one of its teams /
    memberships."""
    ids: set[int] = set()
    # team memberships
    for team in db.scalars(
        select(EventTeam)
        .join(EventTeamMember, EventTeamMember.team_id == EventTeam.id)
        .where(EventTeamMember.user_id == user.id)
    ):
        ids.add(team.category.event_id)
    # role seats the user occupies (entity_type/entity_id → event)
    seats = db.scalars(
        select(Position)
        .join(PositionOccupant, PositionOccupant.position_id == Position.id)
        .where(PositionOccupant.user_id == user.id, Position.entity_type.is_not(None))
    )
    for pos in seats:
        if pos.entity_type == "event":
            ids.add(pos.entity_id)
        elif pos.entity_type == "team":
            team = db.get(EventTeam, pos.entity_id)
            if team is not None:
                ids.add(team.category.event_id)
        elif pos.entity_type == "membership":
            m = db.get(EventTeamMember, pos.entity_id)
            if m is not None:
                ids.add(m.team.category.event_id)
    return ids


def _events(db: Session, user: User, scope: str, start, end) -> list[CalendarItem]:
    if not access.has_privilege(db, user, "events.view"):
        return []
    query = select(Event).where(Event.status == EventStatus.ACTIVE)
    if scope == "me":
        mine = _my_event_ids(db, user)
        if not mine:
            return []
        query = query.where(Event.id.in_(mine))
    out = []
    for comp in db.scalars(query):
        # a dateless event isn't placeable on a calendar; skip it
        if comp.start_date is None and comp.end_date is None:
            continue
        s = comp.start_date or comp.end_date
        e = comp.end_date or comp.start_date
        # keep it if its span overlaps the requested window at all
        if end is not None and s > end:
            continue
        if start is not None and e < start:
            continue
        out.append(CalendarItem(
            source="event", id=comp.id, title=comp.name, start=s, end=e if e != s else None,
            kind=comp.kind.name if comp.kind else None,
        ))
    return out


def _inventory(db: Session, user: User, scope: str, start, end) -> list[CalendarItem]:
    if not access.has_privilege(db, user, "inventory.view"):
        return []
    query = select(InventoryRequest)
    if scope == "me" or not access.has_privilege(db, user, "inventory.approve"):
        query = query.where(InventoryRequest.requester_id == user.id)
    out = []
    for req in db.scalars(query):
        title = f"{req.item.name} ×{req.quantity}" if req.item else f"Request #{req.id}"
        # a checkout can put two marks on the calendar: needed-by and return-by
        if _in_window(req.needed_by, start, end) and req.status in (
            InventoryRequestStatus.SUBMITTED, InventoryRequestStatus.APPROVED
        ):
            out.append(CalendarItem(
                source="inventory", id=req.id, title=title, start=req.needed_by,
                kind="needed", detail=req.requester.full_name if req.requester else None,
            ))
        if _in_window(req.return_by, start, end) and req.status == InventoryRequestStatus.ISSUED:
            out.append(CalendarItem(
                source="inventory", id=req.id, title=title, start=req.return_by,
                kind="return", overdue=req.is_overdue,
                detail=req.requester.full_name if req.requester else None,
            ))
    return out


def _requests(db: Session, user: User, scope: str, start, end) -> list[CalendarItem]:
    if not access.has_privilege(db, user, "tasks.use"):
        return []
    query = select(WorkRequest).where(WorkRequest.due_date.is_not(None))
    # work requests are private to their two parties; general shows all only
    # for a top-level user, otherwise it's the same as "me"
    if scope == "me" or not access.is_top(db, user):
        query = query.where(
            or_(WorkRequest.requester_id == user.id, WorkRequest.recipient_id == user.id)
        )
    if start is not None:
        query = query.where(WorkRequest.due_date >= start)
    if end is not None:
        query = query.where(WorkRequest.due_date <= end)
    out = []
    for r in db.scalars(query):
        out.append(CalendarItem(
            source="request", id=r.id, title=r.title, start=r.due_date, kind=r.status,
        ))
    return out


_FETCHERS = {
    "tasks": _tasks,
    "events": _events,
    "inventory": _inventory,
    "requests": _requests,
}


def gather(
    db: Session, user: User, *, scope: str, sources: list[str],
    start: date | None, end: date | None,
) -> list[CalendarItem]:
    scope = "me" if scope == "me" else "general"
    items: list[CalendarItem] = []
    for src in sources:
        fetch = _FETCHERS.get(src)
        if fetch is not None:
            items.extend(fetch(db, user, scope, start, end))
    items.sort(key=lambda i: (i.start, i.source, i.title))
    return items
