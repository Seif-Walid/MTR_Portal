"""The AI assistant's tools — the only things it can do to the portal.

Every tool runs as the person who owns the AI session, through the same
service functions the HTTP routes use, so the assistant can never do more
than that person could by hand.

Read tools run immediately. Write tools never run when the AI calls them:
they are dry-run (to catch "not enough stock" or a missing permission early),
rolled back, and stored as a pending action the person confirms in the
portal. A write can build on an earlier pending one — `event_from_action: 12`
means "the event that action #12 creates" — resolved when they are confirmed
together.
"""

from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Callable, Literal

from fastapi import HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import viewer
from app.domains.access import service as access
from app.domains.ai import actions
from app.domains.ai import search as semantic
from app.domains.events import router as events_router
from app.domains.events.models import Event, EventCategory, EventKind, EventStatus, EventTeam
from app.domains.events.schemas import EventCreate, MemberAdd, TeamCreate
from app.domains.events.service import can_manage_entity, require_manage_event, require_view
from app.domains.finance import service as finance_service
from app.domains.finance.models import BudgetLine, Currency, FinanceSeason, SeasonStatus
from app.domains.inventory import router as inventory_router
from app.domains.inventory.models import AllocationPurpose
from app.domains.inventory.schemas import ItemOut
from app.domains.inventory.service import get_item_or_404
from app.domains.positions import role_engine
from app.domains.positions.models import Position
from app.domains.positions.service import resync_managers
from app.domains.tasks import router as tasks_router
from app.domains.tasks.models import TaskPriority
from app.domains.tasks.schemas import TaskCreate
from app.domains.users.models import User


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


@dataclass
class Tool:
    name: str
    description: str
    input_model: type[BaseModel]
    kind: Literal["read", "write"]
    run: Callable[..., Any]  # read: (db, user, inp) ; write: (db, user, inp, refs)
    summarize: Callable[[Session, BaseModel], str] | None = None
    needs_conversation: bool = False  # read tools that store a file for this chat

    def schema(self) -> dict:
        s = self.input_model.model_json_schema()
        s.pop("title", None)
        return s


def _json(value: Any) -> Any:
    """Round-trip through JSON so results are plain data (dates → strings)."""
    return json.loads(json.dumps(value, default=str))


def _ref(refs: dict[int, dict], action_id: int | None, key: str) -> int | None:
    if action_id is None:
        return None
    result = refs.get(action_id)
    if result is None or key not in result:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Action #{action_id} must be confirmed in the same batch (it provides {key})",
        )
    return result[key]


def _name(db: Session, model, oid: int | None, attr: str = "name") -> str:
    if oid is None:
        return "?"
    obj = db.get(model, oid)
    return getattr(obj, attr) if obj is not None else f"#{oid}"


# =============================================================== read tools
class SearchIn(_In):
    query: str = Field(description="What to look for, in plain words, e.g. 'buck driver' or 'ROV thrusters'")
    types: list[Literal["inventory", "event", "team", "person", "budget_line"]] | None = Field(
        default=None, description="Restrict to these record types; omit to search all")
    limit: int = Field(default=10, ge=1, le=50)


def _search(db: Session, user: User, inp: SearchIn) -> dict:
    return {"results": semantic.search(db, user, inp.query, inp.types, inp.limit)}


class FindPersonIn(_In):
    name: str = Field(description="A person's name as the user typed it; spelling may be off")


def _find_person(db: Session, user: User, inp: FindPersonIn) -> dict:
    access.require_privilege(db, user, "people.view")
    target = inp.name.lower().strip()
    scored = []
    for person in db.scalars(select(User).where(User.is_active)):
        name = person.full_name.lower()
        score = max(
            difflib.SequenceMatcher(None, target, name).ratio(),
            # first+last name in any order, tolerant of one-letter slips
            sum(max((difflib.SequenceMatcher(None, w, n).ratio() for n in name.split()), default=0)
                for w in target.split()) / max(len(target.split()), 1),
        )
        scored.append((score, person))
    scored.sort(key=lambda s: s[0], reverse=True)
    contacts = viewer.sees_contacts(access.privileges_for(db, user))
    return {"matches": [
        {"user_id": p.id, "name": p.full_name, "department": p.department,
         "email": p.email if contacts or p.id == user.id else None,
         "score": round(s, 3)}
        for s, p in scored[:5] if s >= 0.5
    ], "note": "If more than one match is plausible, ask the user which person they mean."}


class ListEventsIn(_In):
    include_archived: bool = False


def _list_events(db: Session, user: User, inp: ListEventsIn) -> dict:
    require_view(db, user)
    q = select(Event)
    if not inp.include_archived:
        q = q.where(Event.status == EventStatus.ACTIVE)
    return {"events": [
        {"event_id": e.id, "name": e.name, "full_name": e.full_name, "kind": e.kind.name if e.kind else None,
         "start_date": e.start_date, "end_date": e.end_date, "status": e.status}
        for e in db.scalars(q.order_by(Event.name))
    ], "kinds": [{"kind_id": k.id, "name": k.name} for k in db.scalars(select(EventKind).order_by(EventKind.sort_order))]}


class EventIdIn(_In):
    event_id: int


def _get_event(db: Session, user: User, inp: EventIdIn) -> dict:
    require_view(db, user)
    comp = db.get(Event, inp.event_id)
    if comp is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Event not found")
    detail = events_router._detail_out(db, user, comp).model_dump()
    roles = [
        {"position_id": p.id, "title": p.title, "occupants": [u.full_name for u in p.occupants]}
        for p in db.scalars(select(Position).where(Position.entity_type == "event", Position.entity_id == comp.id))
    ]
    out = {"event": detail, "roles": roles}
    if access.has_privilege(db, user, "finance.view"):
        out["money"] = finance_service.event_money(db, comp.id)
    return out


class ItemIdIn(_In):
    item_id: int


def _item(db: Session, user: User, inp: ItemIdIn) -> dict:
    return ItemOut.model_validate(get_item_or_404(db, user, inp.item_id)).model_dump()


class BudgetQueryIn(_In):
    event_id: int | None = Field(default=None, description="Only this event's lines; omit for all")


def _budget(db: Session, user: User, inp: BudgetQueryIn) -> dict:
    access.require_privilege(db, user, "finance.view")
    q = select(BudgetLine)
    if inp.event_id is not None:
        q = q.where(BudgetLine.event_id == inp.event_id)
    seasons = db.scalars(select(FinanceSeason).order_by(FinanceSeason.id.desc()))
    return {
        "lines": [
            {"id": b.id, "event_id": b.event_id, "item": b.item, "unit_price_egp": b.unit_price_egp,
             "total_qty": b.total_qty, "in_stock_qty": b.in_stock_qty, "fmv": b.fmv,
             "needed_cost": b.needed_cost, "season_id": b.season_id}
            for b in db.scalars(q.limit(300))
        ],
        "seasons": [{"season_id": s.id, "name": s.name, "status": s.status, "usd_rate": s.usd_rate} for s in seasons],
    }


class PriceIn(_In):
    name: str = Field(description="Part name to price at Egyptian shops (Makers, Future Electronics)")


def _price(db: Session, user: User, inp: PriceIn) -> dict:
    from app.domains.inventory import pricing

    if not any(access.has_privilege(db, user, k) for k in ("inventory.view", "inventory.edit", "finance.view")):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No access to prices")
    return pricing.search(inp.name, limit=5)


class NoIn(_In):
    pass


def _pending(db: Session, user: User, inp: NoIn) -> dict:
    from app.domains.ai.models import ActionStatus, AiPendingAction

    rows = db.scalars(select(AiPendingAction).where(
        AiPendingAction.user_id == user.id, AiPendingAction.status == ActionStatus.PENDING
    ).order_by(AiPendingAction.id))
    return {"pending": [{"action_id": a.id, "tool": a.tool, "summary": a.summary} for a in rows],
            "note": "Only the user can confirm these, from the portal's Assistant page."}


# ============================================================== write tools
def _resolve_kind(db: Session, kind: str | None) -> int | None:
    if not kind:
        return None
    kinds = list(db.scalars(select(EventKind)))
    for k in kinds:
        if k.name.lower() == kind.lower() or k.slug == kind.lower():
            return k.id
    raise HTTPException(status.HTTP_400_BAD_REQUEST,
                        f"Unknown event kind '{kind}'. Known: {', '.join(k.name for k in kinds)}")


class CreateEventIn(_In):
    name: str = Field(min_length=1, max_length=255, description="Short name, e.g. 'MRC'")
    full_name: str | None = Field(default=None, description="Long name, e.g. 'Makers Robotics Competition'")
    kind: str | None = Field(default=None, description="Event kind name (e.g. Competition, Training, R&D); default is the first kind")
    description: str = ""
    start_date: date | None = None
    end_date: date | None = None
    manager_user_id: int | None = Field(default=None, description="Person who manages the event (from find_person)")
    manager_role: str | None = Field(default=None, description="Which automatic role seat to fill, e.g. 'PM'; default: the seat that can manage the event")


def _manager_seat(db: Session, event_id: int, hint: str | None) -> Position | None:
    seats = list(db.scalars(select(Position).where(Position.entity_type == "event", Position.entity_id == event_id)))
    if hint:
        for seat in seats:
            if hint.lower() in seat.title.lower():
                return seat
    for seat in seats:
        if seat.access_level is not None and "events.manage_seated" in json.loads(seat.access_level.privileges or "[]"):
            return seat
    return seats[0] if seats else None


def _create_event(db: Session, user: User, inp: CreateEventIn, refs: dict) -> dict:
    comp = events_router.do_create_event(db, user, EventCreate(
        name=inp.name, full_name=inp.full_name, kind_id=_resolve_kind(db, inp.kind),
        description=inp.description, start_date=inp.start_date, end_date=inp.end_date,
    ))
    out = {"event_id": comp.id, "name": comp.name}
    if inp.manager_user_id is not None:
        if db.get(User, inp.manager_user_id) is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Manager not found")
        seat = _manager_seat(db, comp.id, inp.manager_role)
        if seat is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "This event kind has no automatic role seats, so there is no manager seat to fill")
        if not access.has_privilege(db, user, "org.edit") and not can_manage_entity(db, user, "event", comp.id):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You may create events but not appoint their managers")
        role_engine.set_position_occupants(db, seat, [inp.manager_user_id])
        resync_managers(db)
        out["manager_seat"] = seat.title
    return out


def _sum_create_event(db: Session, inp: CreateEventIn) -> str:
    s = f"Create event **{inp.name}**" + (f" ({inp.full_name})" if inp.full_name else "")
    if inp.kind:
        s += f" as {inp.kind}"
    if inp.start_date:
        s += f", {inp.start_date}" + (f" → {inp.end_date}" if inp.end_date else "")
    if inp.manager_user_id:
        s += f", managed by {_name(db, User, inp.manager_user_id, 'full_name')}"
    return s


class CreateTeamIn(_In):
    name: str = Field(min_length=1, max_length=255)
    event_id: int | None = None
    event_from_action: int | None = Field(default=None, description="Pending action id that creates the event")
    category: str = Field(default="General", description="Category (division) inside the event; created if missing")
    member_user_ids: list[int] = Field(default_factory=list)


def _create_team(db: Session, user: User, inp: CreateTeamIn, refs: dict) -> dict:
    event_id = inp.event_id or _ref(refs, inp.event_from_action, "event_id")
    if event_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Give event_id or event_from_action")
    require_manage_event(db, user, event_id)
    cat = db.scalar(select(EventCategory).where(
        EventCategory.event_id == event_id, EventCategory.name == inp.category))
    if cat is None:
        cat = EventCategory(event_id=event_id, name=inp.category)
        db.add(cat)
        db.flush()
    team = events_router.do_add_team(db, user, cat.id, TeamCreate(name=inp.name))
    for uid in inp.member_user_ids:
        events_router.do_add_member(db, user, team.id, MemberAdd(user_id=uid))
    return {"team_id": team.id, "event_id": event_id, "name": team.name}


def _sum_create_team(db: Session, inp: CreateTeamIn) -> str:
    where = _name(db, Event, inp.event_id) if inp.event_id else f"the event from #{inp.event_from_action}"
    s = f"Create team **{inp.name}** in {where} / {inp.category}"
    if inp.member_user_ids:
        s += " with " + ", ".join(_name(db, User, u, "full_name") for u in inp.member_user_ids)
    return s


class AddMembersIn(_In):
    team_id: int | None = None
    team_from_action: int | None = None
    user_ids: list[int] = Field(min_length=1)


def _add_members(db: Session, user: User, inp: AddMembersIn, refs: dict) -> dict:
    team_id = inp.team_id or _ref(refs, inp.team_from_action, "team_id")
    if team_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Give team_id or team_from_action")
    added = [uid for uid in inp.user_ids if events_router.do_add_member(db, user, team_id, MemberAdd(user_id=uid))[1]]
    return {"team_id": team_id, "added": added}


def _sum_add_members(db: Session, inp: AddMembersIn) -> str:
    team = _name(db, EventTeam, inp.team_id) if inp.team_id else f"the team from #{inp.team_from_action}"
    return f"Add {', '.join(_name(db, User, u, 'full_name') for u in inp.user_ids)} to team **{team}**"


class AllocLine(_In):
    item_id: int
    quantity: int = Field(ge=1)


class AllocateIn(_In):
    lines: list[AllocLine] = Field(min_length=1)
    event_id: int | None = None
    event_from_action: int | None = None
    team_id: int | None = Field(default=None, description="Event team receiving the parts (implies its event)")
    team_from_action: int | None = None
    holder_user_id: int | None = Field(default=None, description="Person physically holding the parts")
    purpose: AllocationPurpose | None = Field(default=None, description="Default: event when an event/team is given")
    notes: str = ""


def _allocate(db: Session, user: User, inp: AllocateIn, refs: dict) -> dict:
    event_id = inp.event_id or _ref(refs, inp.event_from_action, "event_id")
    team_id = inp.team_id or _ref(refs, inp.team_from_action, "team_id")
    purpose = inp.purpose or (AllocationPurpose.EVENT if (event_id or team_id) else AllocationPurpose.OTHER)
    items = inventory_router.do_allocate(
        db, user, [(line.item_id, line.quantity) for line in inp.lines], purpose=purpose,
        event_id=event_id, event_team_id=team_id, holder_id=inp.holder_user_id,
        notes=inp.notes or "Allocated via AI assistant",
    )
    return {"items": [{"item_id": i.id, "name": i.name, "free_after": i.free} for i in items]}


def _sum_allocate(db: Session, inp: AllocateIn) -> str:
    from app.domains.inventory.models import InventoryItem

    parts = ", ".join(f"{line.quantity}× {_name(db, InventoryItem, line.item_id)}" for line in inp.lines)
    if inp.team_id:
        team = db.get(EventTeam, inp.team_id)
        to = f"team **{team.name}** ({team.category.event.name})" if team else f"team #{inp.team_id}"
    elif inp.team_from_action:
        to = f"the team from #{inp.team_from_action}"
    elif inp.event_id:
        to = f"event **{_name(db, Event, inp.event_id)}**"
    elif inp.event_from_action:
        to = f"the event from #{inp.event_from_action}"
    else:
        to = "general use"
    s = f"Allocate {parts} to {to}"
    if inp.holder_user_id:
        s += f", held by {_name(db, User, inp.holder_user_id, 'full_name')}"
    return s


class TasksIn(_In):
    title: str = Field(min_length=1, max_length=255)
    description: str = ""
    assignee_ids: list[int] = Field(default_factory=list, description="People to assign; empty + team = whole team")
    team_id: int | None = None
    team_from_action: int | None = None
    team_visible: bool = False
    due_date: date | None = None
    priority: TaskPriority = TaskPriority.MEDIUM
    category: str | None = None


def _tasks(db: Session, user: User, inp: TasksIn, refs: dict) -> dict:
    team_id = inp.team_id or _ref(refs, inp.team_from_action, "team_id")
    tasks = tasks_router.do_create_tasks(db, user, TaskCreate(
        title=inp.title, description=inp.description, assignee_ids=inp.assignee_ids,
        event_team_id=team_id, team_visible=inp.team_visible, due_date=inp.due_date,
        priority=inp.priority, category=inp.category,
    ))
    return {"task_ids": [t.id for t in tasks], "assignees": [t.assignee.full_name for t in tasks]}


def _sum_tasks(db: Session, inp: TasksIn) -> str:
    who = ", ".join(_name(db, User, u, "full_name") for u in inp.assignee_ids)
    if not who:
        who = ("team " + _name(db, EventTeam, inp.team_id)) if inp.team_id else f"the team from #{inp.team_from_action}"
    s = f"Task **{inp.title}** → {who}"
    if inp.due_date:
        s += f", due {inp.due_date}"
    return s + f" ({inp.priority} priority)"


class BudgetLineIn(_In):
    item: str = Field(min_length=1, max_length=255)
    unit_price: float = Field(ge=0)
    currency: Currency = Currency.EGP
    required_qty: float = Field(default=1, ge=0)
    spare_qty: float = Field(default=0, ge=0)
    in_stock_qty: float = Field(default=0, ge=0, description="How many we already own (from inventory)")
    link_note: str | None = Field(default=None, description="Source URL or note for the price")


class BudgetIn(_In):
    lines: list[BudgetLineIn] = Field(min_length=1)
    event_id: int | None = None
    event_from_action: int | None = None
    season_id: int | None = Field(default=None, description="Finance season; default is the newest active one")


def _budget_write(db: Session, user: User, inp: BudgetIn, refs: dict) -> dict:
    access.require_privilege(db, user, "finance.edit")
    event_id = inp.event_id or _ref(refs, inp.event_from_action, "event_id")
    season_id = inp.season_id
    if season_id is None:
        season = db.scalar(select(FinanceSeason).where(FinanceSeason.status == SeasonStatus.ACTIVE)
                           .order_by(FinanceSeason.id.desc()))
        if season is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "No active finance season — give season_id")
        season_id = season.id
    elif db.get(FinanceSeason, season_id) is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Season not found")
    ids = []
    for line in inp.lines:
        row = BudgetLine(season_id=season_id, event_id=event_id, **line.model_dump())
        db.add(row)
        db.flush()
        ids.append(row.id)
    from app.domains.audit.service import log as audit_log

    audit_log(db, user.id, "finance", "budget_lines_added", "event", event_id, {"count": len(ids), "via": "ai"})
    return {"budget_line_ids": ids, "event_id": event_id, "season_id": season_id}


def _sum_budget(db: Session, inp: BudgetIn) -> str:
    total = sum((line.required_qty + line.spare_qty - line.in_stock_qty) * line.unit_price
                for line in inp.lines if line.required_qty + line.spare_qty > line.in_stock_qty)
    where = _name(db, Event, inp.event_id) if inp.event_id else f"the event from #{inp.event_from_action}"
    cur = inp.lines[0].currency if len({line.currency for line in inp.lines}) == 1 else "mixed"
    return f"Add {len(inp.lines)} budget line(s) to **{where}** (still to buy ≈ {total:,.0f} {cur})"


# =================================================================== registry
# ------------------------------------------------- data & documents (general)
class QueryIn(_In):
    sql: str = Field(max_length=20_000, description="One read-only SQLite SELECT (or WITH … SELECT) over tables from data_schema")
    limit: int = Field(default=200, ge=1, le=2000)


class Block(_In):
    """Exactly one of: text, table, for_each, page_break."""
    text: str | None = Field(default=None, description="Markdown. {{column}} inserts a value from the enclosing for_each row")
    table: str | None = Field(default=None, description="SQL SELECT rendered as a table (a sheet in Excel). Use :column for values of the enclosing for_each row")
    heading: str | None = Field(default=None, description="Title above a table (sheet name in Excel); {{column}} allowed")
    empty: str | None = Field(default=None, description="What to print when the table query returns no rows")
    for_each: str | None = Field(default=None, description="SQL SELECT; `blocks` repeat once per row")
    blocks: list["Block"] | None = None
    new_page: bool = Field(default=True, description="for_each: start each row on a new page (PDF)")
    page_break: bool = False

    @model_validator(mode="after")
    def _one_kind(self):
        kinds = [k for k in ("text", "table", "for_each") if getattr(self, k) is not None] + (["page_break"] if self.page_break else [])
        if len(kinds) != 1:
            raise ValueError(f"each block needs exactly one of text / table / for_each / page_break, got {kinds or 'none'} — split it into separate blocks")
        if self.blocks is not None and not self.for_each:
            raise ValueError("`blocks` only goes inside a for_each block")
        return self


Block.model_rebuild()


class DocumentIn(_In):
    format: Literal["pdf", "xlsx"]
    filename: str = Field(max_length=120)
    title: str = Field(max_length=200)
    blocks: list[Block] = Field(min_length=1, max_length=200)


def _schema(db: Session, user: User, inp: NoIn) -> dict:
    from app.domains.ai import data

    return {"dialect": "SQLite", "tables": data.schema(db, user)}


def _query(db: Session, user: User, inp: QueryIn) -> dict:
    from app.domains.ai import data

    return data.query(db, user, inp.sql, inp.limit)


def _document(db: Session, user: User, inp: DocumentIn, conversation_id: int | None) -> dict:
    from app.domains.ai import files

    blocks = [b.model_dump(exclude_none=True) for b in inp.blocks]
    return files.make_document(db, user, conversation_id, fmt=inp.format, filename=inp.filename,
                               title=inp.title, blocks=blocks)


TOOLS: dict[str, Tool] = {t.name: t for t in [
    Tool("semantic_search", "Search portal records by meaning, not exact words: inventory parts (finds 'step-down converter' for 'buck driver'), events, teams, people, budget lines. Use this first to turn names in the user's request into ids.", SearchIn, "read", _search),
    Tool("find_person", "Find a person's user_id from a name, tolerating misspellings. Always use before assigning or appointing anyone.", FindPersonIn, "read", _find_person),
    Tool("list_events", "List events (competitions, trainings, R&D) and the available event kinds.", ListEventsIn, "read", _list_events),
    Tool("get_event", "Full detail of one event: categories, teams with members, role seats, and money if visible.", EventIdIn, "read", _get_event),
    Tool("get_inventory_item", "One inventory item: quantity owned, free, in use, value and current allocations.", ItemIdIn, "read", _item),
    Tool("list_budget", "Budget lines (planned purchases) and finance seasons; use for cost questions.", BudgetQueryIn, "read", _budget),
    Tool("price_lookup", "Live prices for a part at Egyptian electronics shops. Slow; use for parts we don't own or have no value for.", PriceIn, "read", _price),
    Tool("list_pending_actions", "Actions you proposed that still wait for the user's confirmation.", NoIn, "read", _pending),
    Tool("data_schema", "Every portal table this user may read, with its columns. Use before query_data / make_document.", NoIn, "read", _schema),
    Tool("query_data", "Run one read-only SQLite SELECT over the portal's data (joins, counts, filters) with the user's own visibility. Use it to answer questions and to check queries before building a document.", QueryIn, "read", _query),
    Tool("make_document", "Make a PDF or Excel file for the user. Describe it as blocks: `text` (markdown), `table` (a SQL query rendered as a table / sheet), `for_each` (a SQL query whose `blocks` repeat per row, e.g. one page per event; inside, {{col}} in text and :col in SQL refer to that row) and `page_break`. All data comes from SQL, so never type records in yourself. Returns a download link.", DocumentIn, "read", _document, needs_conversation=True),
    Tool("find_actions", "Look up ANY action a person can take on the portal's pages (record a payment, edit a task, delete an item, change a member, approve a request, ...) and what it needs. Use it whenever no other tool fits the request.", actions.FindActionsIn, "read", actions.find_actions),
    Tool("portal_read", "Run a GET action from find_actions and return its data, as this user sees it on the page.", actions.ReadIn, "read", actions.portal_read),
    Tool("portal_change", "PROPOSE any POST / PUT / PATCH / DELETE action from find_actions. It is checked against the real page (permissions, validation) but only runs after the user confirms.", actions.ChangeIn, "write", actions.portal_change, actions.summarize_change),
    Tool("create_event", "PROPOSE creating an event, optionally appointing its manager. Not executed until the user confirms.", CreateEventIn, "write", _create_event, _sum_create_event),
    Tool("create_team", "PROPOSE creating a team inside an event (and adding members).", CreateTeamIn, "write", _create_team, _sum_create_team),
    Tool("add_team_members", "PROPOSE adding people to an event team.", AddMembersIn, "write", _add_members, _sum_add_members),
    Tool("allocate_inventory", "PROPOSE giving inventory to an event, an event team or a person. Checks free stock.", AllocateIn, "write", _allocate, _sum_allocate),
    Tool("create_tasks", "PROPOSE assigning a task to people or to a whole event team.", TasksIn, "write", _tasks, _sum_tasks),
    Tool("create_budget_lines", "PROPOSE adding planned purchases (budget lines) to an event.", BudgetIn, "write", _budget_write, _sum_budget),
]}


_PROPOSE_CLAUSES = re.compile(
    r"\s*(Not executed until the user confirms\.|,? but only runs after the user confirms|"
    r"Actions you proposed that still wait for the user's confirmation\.)")


def _direct_description(t: Tool) -> str:
    """Wording for agents whose writes run at once (no confirmation step)."""
    if t.kind != "write":
        return t.description
    text = _PROPOSE_CLAUSES.sub("", t.description.removeprefix("PROPOSE ")).strip()
    first, _, rest = text.partition(" ")
    verb = {"creating": "Create", "adding": "Add", "giving": "Give", "assigning": "Assign"}.get(first.lower(), first.capitalize())
    return f"{verb} {rest} Runs immediately as the signed-in person; the result has the real ids."


def catalog(direct: bool = False) -> list[dict]:
    return [{"name": t.name, "description": _direct_description(t) if direct else t.description,
             "kind": t.kind, "input_schema": t.schema()}
            for t in TOOLS.values() if not (direct and t.name == "list_pending_actions")]
