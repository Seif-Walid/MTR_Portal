"""The Home dashboard: a role-aware, me-scoped roll-up of everything that
needs the signed-in person right now, gathered from across the portal (tasks,
work requests, inventory returns, events) into urgency-ordered buckets.

Same foundations as the calendar aggregator, but organized for triage: fixed
buckets (overdue / needs-review / waiting-on-you / due-today / this-week) with
counts, capped item previews, and a role-adaptive shape — a reviewer also sees
the review queue. Every source respects the same view privileges as the rest
of the app; a person who can't touch a source simply never sees it.
"""

from datetime import date, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.domains.access import service as access
from app.domains.dashboard.schemas import (
    Dashboard,
    DashboardItem,
    DashboardSection,
    DashboardStat,
)
from app.domains.hierarchy.service import can_review_task
from app.domains.inventory.models import InventoryRequest, InventoryRequestStatus
from app.domains.requests.models import RequestStatus, WorkRequest
from app.domains.tasks.models import Task, TaskStatus
from app.domains.users.models import User

PREVIEW_CAP = 6  # items shown per bucket before "see all"
WEEK = 7  # "this week" horizon, in days

_PRIORITY_RANK = {"urgent": 0, "high": 1, "medium": 2, "low": 3}


def _first_name(full_name: str) -> str:
    return full_name.strip().split(" ")[0] if full_name.strip() else full_name


def _task_item(t: Task, *, action: str = "Open") -> DashboardItem:
    return DashboardItem(
        source="task",
        id=t.id,
        title=t.title,
        detail=t.assigner.full_name if t.assigner else None,
        due=t.due_date,
        overdue=t.due_date is not None and t.due_date < date.today()
        and t.status != TaskStatus.APPROVED,
        blocked=t.is_blocked,
        status=t.status,
        priority=t.priority,
        action=action,
    )


def _return_item(r: InventoryRequest) -> DashboardItem:
    title = f"{r.item.name} ×{r.quantity}" if r.item else f"Request #{r.id}"
    return DashboardItem(
        source="inventory",
        id=r.id,
        title=title,
        detail="Return due",
        due=r.return_by,
        overdue=bool(r.is_overdue),
        status="issued",
        action="Return",
    )


def _sort_key(item: DashboardItem):
    return (
        item.due or date.max,
        _PRIORITY_RANK.get(item.priority or "", 2),
        item.title.lower(),
    )


def build(db: Session, user: User) -> Dashboard:
    today = date.today()
    week_end = today + timedelta(days=WEEK)

    can_tasks = access.has_privilege(db, user, "tasks.use")
    can_inventory = access.has_privilege(db, user, "inventory.view")

    # ---- my open tasks (assigned to me, not yet approved) ----
    my_tasks: list[Task] = []
    if can_tasks:
        my_tasks = list(
            db.scalars(
                select(Task).where(
                    Task.assignee_id == user.id,
                    Task.status != TaskStatus.APPROVED,
                )
            ).unique()
        )

    # ---- my inventory returns still out on loan ----
    my_returns: list[InventoryRequest] = []
    if can_inventory:
        my_returns = list(
            db.scalars(
                select(InventoryRequest).where(
                    InventoryRequest.requester_id == user.id,
                    InventoryRequest.status == InventoryRequestStatus.ISSUED,
                    InventoryRequest.return_by.is_not(None),
                )
            )
        )

    # ---- bucket the dated obligations by urgency across sources ----
    overdue: list[DashboardItem] = []
    today_items: list[DashboardItem] = []
    week_items: list[DashboardItem] = []

    def place(item: DashboardItem) -> None:
        if item.due is None:
            return
        if item.due < today:
            overdue.append(item)
        elif item.due == today:
            today_items.append(item)
        elif item.due <= week_end:
            week_items.append(item)

    for t in my_tasks:
        place(_task_item(t))
    for r in my_returns:
        item = _return_item(r)
        # an overdue return has a null/past return_by handled by is_overdue
        if item.overdue and item.due is not None and item.due < today:
            overdue.append(item)
        else:
            place(item)

    # ---- needs your review (reviewer only): submitted tasks I can approve ----
    review_items: list[DashboardItem] = []
    is_reviewer = access.has_privilege(db, user, "tasks.assign")
    if can_tasks:
        for t in db.scalars(
            select(Task).where(Task.status == TaskStatus.SUBMITTED)
        ).unique():
            if can_review_task(db, user, t.assigner_id):
                is_reviewer = True
                item = _task_item(t, action="Review")
                item.detail = t.assignee.full_name if t.assignee else None
                review_items.append(item)

    # ---- work requests waiting on my response ----
    waiting_items: list[DashboardItem] = []
    if can_tasks:
        for r in db.scalars(
            select(WorkRequest).where(
                WorkRequest.recipient_id == user.id,
                WorkRequest.status == RequestStatus.PENDING,
            )
        ):
            waiting_items.append(
                DashboardItem(
                    source="request",
                    id=r.id,
                    title=r.title,
                    detail=r.requester.full_name if r.requester else None,
                    due=r.due_date,
                    overdue=r.due_date is not None and r.due_date < today,
                    status=r.status,
                    priority=r.priority,
                    action="Respond",
                )
            )

    for bucket in (overdue, today_items, week_items, review_items, waiting_items):
        bucket.sort(key=_sort_key)

    def section(key: str, label: str, tone: str, items: list[DashboardItem]) -> DashboardSection:
        return DashboardSection(
            key=key, label=label, tone=tone,
            count=len(items), items=items[:PREVIEW_CAP],
        )

    raw = [
        section("overdue", "Overdue", "danger", overdue),
        section("review", "Needs your review", "normal", review_items),
        section("waiting", "Waiting on you", "normal", waiting_items),
        section("today", "Due today", "normal", today_items),
        section("week", "This week", "normal", week_items),
    ]
    sections = [s for s in raw if s.count > 0]

    # stat tiles mirror the buckets; keep the reviewer tile only for reviewers
    counts = {s.key: s.count for s in raw}
    stat_defs = [
        ("overdue", "Overdue", "danger"),
        ("today", "Due today", "normal"),
        ("week", "This week", "normal"),
    ]
    if is_reviewer:
        stat_defs.insert(1, ("review", "Needs review", "normal"))
    if can_tasks:
        stat_defs.append(("waiting", "Waiting on you", "normal"))
    stats = [
        DashboardStat(
            key=k, label=label, count=counts.get(k, 0),
            tone="danger" if (tone == "danger" and counts.get(k, 0) > 0) else "normal",
        )
        for k, label, tone in stat_defs
    ]

    return Dashboard(
        as_of=today,
        greeting_name=_first_name(user.full_name),
        is_reviewer=is_reviewer,
        all_clear=not sections,
        stats=stats,
        sections=sections,
    )
