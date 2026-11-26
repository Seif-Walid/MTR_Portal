"""The finance books over HTTP: computed views (finance.view), logging money
as the signed-in holder (finance.handle_cash) and the season setup
(finance.edit). The raw tables stay editable in the Advanced grids
(bulk/registry.py, finance.edit) for corrections."""

from datetime import date
from typing import Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.domains.access import service as access
from app.domains.audit import service as audit
from app.domains.auth.deps import DB, CurrentUser
from app.domains.events.models import Event, EventTeam
from app.domains.finance import entries, service
from app.domains.finance.models import (
    DuesTier,
    FinanceOption,
    FinanceParty,
    FinanceSeason,
    FundingLine,
    OptionList,
)
from app.domains.users.models import User

router = APIRouter(prefix="/finance", tags=["finance"])


def _season_or_current(db: DB, season_id: int | None) -> FinanceSeason:
    season = db.get(FinanceSeason, season_id) if season_id is not None else service.current_season(db)
    if season is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such season")
    return season


@router.get("/seasons")
def list_seasons(db: DB, user: CurrentUser) -> dict:
    access.require_privilege(db, user, "finance.view")
    current = service.current_season(db)
    return {
        "seasons": [service._season_out(s) for s in service.seasons(db)],
        "current_id": current.id if current else None,
    }


@router.get("/dashboard")
def dashboard(db: DB, user: CurrentUser, season_id: int | None = None) -> dict:
    """Roll-up of the books. Omit season_id for every season together."""
    access.require_privilege(db, user, "finance.view")
    if season_id is not None and db.get(FinanceSeason, season_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such season")
    return service.dashboard(db, season_id)


@router.get("/dues")
def dues(db: DB, user: CurrentUser, season_id: int | None = None) -> dict:
    """The season's dues roster with the monthly payment grid and projection."""
    access.require_privilege(db, user, "finance.view")
    return service.dues_ledger(db, _season_or_current(db, season_id))


@router.get("/cash")
def cash(db: DB, user: CurrentUser) -> dict:
    access.require_privilege(db, user, "finance.view")
    return service.cash_balances(db)


@router.get("/events/{event_id}")
def event_money(event_id: int, db: DB, user: CurrentUser) -> dict:
    access.require_privilege(db, user, "finance.view")
    return service.event_money(db, event_id)


class RollForwardIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)


@router.post("/seasons/{season_id}/roll-forward")
def roll_forward(season_id: int, payload: RollForwardIn, db: DB, user: CurrentUser) -> dict:
    """Start the next season from this one (plan + fee schedule carried over)."""
    access.require_privilege(db, user, "finance.edit")
    source = db.get(FinanceSeason, season_id)
    if source is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such season")
    name = payload.name.strip()
    if db.scalar(select(FinanceSeason.id).where(FinanceSeason.name == name)):
        raise HTTPException(status.HTTP_409_CONFLICT, f"A season called “{name}” already exists")
    season, copied = service.roll_forward(db, source, name)
    audit.log(db, user.id, "finance", "season_rolled_forward", "finance_seasons", season.id,
              {"from": source.id, "copied": copied})
    db.commit()
    return {"id": season.id, "name": season.name, "copied": copied}


# --- logging money (the holder is always the signed-in account) ---------------
def _today() -> date:
    return date.today()


class DuesIn(BaseModel):
    member_id: int
    amount: float
    method_id: int | None = None
    paid_on: date | None = None
    note: str | None = Field(default=None, max_length=2000)


class FundingIn(BaseModel):
    amount: float
    method_id: int | None = None
    received_on: date | None = None
    funding_id: int | None = Field(default=None, description="An expected funding line this money settles.")
    party_id: int | None = None
    party_name: str | None = Field(default=None, max_length=255, description="Creates a new contact with this name when party_id is not given.")
    source: str | None = Field(default=None, max_length=255)
    type_id: int | None = None
    note: str | None = Field(default=None, max_length=2000)


class SpendingIn(BaseModel):
    item: str = Field(min_length=1, max_length=255)
    amount: float | None = None
    count: float | None = None
    unit_cost: float | None = None
    method_id: int | None = None
    spent_on: date | None = None
    event_id: int | None = None
    event_team_id: int | None = None
    category_id: int | None = None
    subcategory_id: int | None = None
    payee_party_id: int | None = None
    payee_name: str | None = Field(default=None, max_length=255)
    receipt: str | None = Field(default=None, max_length=2000)
    note: str | None = Field(default=None, max_length=2000)


class HandoverIn(BaseModel):
    to_user_id: int
    amount: float
    fees: float | None = None
    from_method_id: int | None = None
    to_method_id: int | None = None
    on: date | None = None
    note: str | None = Field(default=None, max_length=2000)


def _edit_any(db: DB, user) -> bool:
    return access.has_privilege(db, user, "finance.edit")


@router.post("/money-in/dues")
def money_in_dues(payload: DuesIn, db: DB, user: CurrentUser) -> dict:
    access.require_privilege(db, user, "finance.handle_cash")
    p = entries.log_dues(db, user, member_id=payload.member_id, amount=payload.amount,
                         method_id=payload.method_id, paid_on=payload.paid_on or _today(), note=payload.note)
    db.commit()
    return {"kind": "dues", "id": p.id}


@router.post("/money-in/funding")
def money_in_funding(payload: FundingIn, db: DB, user: CurrentUser) -> dict:
    access.require_privilege(db, user, "finance.handle_cash")
    f = entries.log_funding(db, user, amount=payload.amount, method_id=payload.method_id,
                            received_on=payload.received_on or _today(), funding_id=payload.funding_id,
                            party_id=payload.party_id, party_name=payload.party_name,
                            source=payload.source, type_id=payload.type_id, note=payload.note)
    db.commit()
    return {"kind": "funding", "id": f.id}


@router.post("/money-out")
def money_out(payload: SpendingIn, db: DB, user: CurrentUser) -> dict:
    access.require_privilege(db, user, "finance.handle_cash")
    s = entries.log_spending(db, user, **{**payload.model_dump(), "spent_on": payload.spent_on or _today()})
    db.commit()
    return {"kind": "spending", "id": s.id}


@router.post("/handover")
def handover(payload: HandoverIn, db: DB, user: CurrentUser) -> dict:
    access.require_privilege(db, user, "finance.handle_cash")
    t = entries.handover(db, user, **{**payload.model_dump(), "on": payload.on or _today()})
    db.commit()
    return {"kind": "handover", "id": t.id}


@router.get("/my-cash")
def my_cash(db: DB, user: CurrentUser) -> dict:
    access.require_privilege(db, user, "finance.view")
    return service.my_cash(db, user)


@router.get("/ledger")
def ledger(db: DB, user: CurrentUser, season_id: int | None = None,
           kind: Literal["dues", "funding", "spending", "handover"] | None = None,
           holder_id: int | None = None, mine: bool = False, limit: int = 300) -> dict:
    access.require_privilege(db, user, "finance.view")
    return entries.ledger(db, user, season_id=season_id, kind=kind, holder_id=holder_id, mine=mine,
                          can_edit_any=_edit_any(db, user), limit=min(max(limit, 1), 2000))


_EDITABLE_DOC = (
    "Change some fields of one logged money entry. The body holds only the fields "
    "to change. Allowed fields per kind — "
    + "; ".join(f"{k}: {', '.join(sorted(v))}" for k, v in entries.EDITABLE.items())
    + ". Dates are YYYY-MM-DD."
)


@router.patch("/entries/{kind}/{entry_id}", description=_EDITABLE_DOC)
def update_entry(kind: Literal["dues", "funding", "spending", "handover"], entry_id: int,
                 payload: dict, db: DB, user: CurrentUser) -> dict:
    access.require_privilege(db, user, "finance.handle_cash")
    for k in ("paid_on", "spent_on", "received_on", "transferred_on"):
        if isinstance(payload.get(k), str):
            try:
                payload[k] = date.fromisoformat(payload[k])
            except ValueError:
                raise HTTPException(422, f"Bad date for {k}")
    entries.update_entry(db, user, kind, entry_id, payload, _edit_any(db, user))
    db.commit()
    return {"ok": True}


@router.delete("/entries/{kind}/{entry_id}")
def delete_entry(kind: Literal["dues", "funding", "spending", "handover"], entry_id: int,
                 db: DB, user: CurrentUser) -> dict:
    access.require_privilege(db, user, "finance.handle_cash")
    entries.delete_entry(db, user, kind, entry_id, _edit_any(db, user))
    return {"ok": True}


@router.get("/form-options")
def form_options(db: DB, user: CurrentUser) -> dict:
    """Everything the money forms pick from, in one call: methods, categories
    (with their sub-categories), funding types, contacts, live events with their
    teams, the other cash holders, and the current season's people who owe dues
    (with what they still owe)."""
    access.require_privilege(db, user, "finance.view")
    opts = list(db.scalars(select(FinanceOption).order_by(FinanceOption.sort_order, FinanceOption.id)))

    def lst(key: str) -> list[dict]:
        return [{"id": o.id, "name": o.value} for o in opts if o.list_key == key]

    events = []
    for ev in db.scalars(select(Event).where(Event.status != "archived").order_by(Event.name)):
        teams = [db.get(EventTeam, tid) for tid in service.event_team_ids(db, ev.id)]
        events.append({"id": ev.id, "name": ev.name,
                       "teams": [{"id": t.id, "name": t.path_name} for t in teams if t is not None]})
    season = service.current_season(db)
    owing = []
    if season is not None:
        for r in service.dues_ledger(db, season)["rows"]:
            owing.append({"member_id": r["member_id"], "name": r["name"], "mtr_id": r["mtr_id"],
                          "tier": r["tier"], "monthly_fee": r["monthly_fee"], "balance": r["balance"],
                          "status": r["status"]})
    holder_ids = service.cash_holder_ids(db)
    holders = [{"id": u.id, "name": u.full_name, "me": u.id == user.id}
               for u in db.scalars(select(User).where(User.id.in_(holder_ids)).order_by(User.full_name))]
    expected = [{"id": f.id, "source": f.source, "amount": f.amount, "season_id": f.season_id}
                for f in db.scalars(select(FundingLine).where(FundingLine.received_on.is_(None)))]
    return {
        "methods": lst(OptionList.PAYMENT_METHOD),
        "categories": lst(OptionList.CATEGORY),
        "subcategories": lst(OptionList.SUBCATEGORY),
        "funding_types": lst(OptionList.FUNDING_TYPE),
        "contacts": [{"id": p.id, "name": p.name} for p in db.scalars(
            select(FinanceParty).where(FinanceParty.is_active, FinanceParty.user_id.is_(None))
            .order_by(FinanceParty.name))],
        "events": events,
        "holders": holders,
        "owing": owing,
        "expected_funding": expected,
        "season": service._season_out(season) if season else None,
        "can_handle_cash": access.has_privilege(db, user, "finance.handle_cash"),
        "can_edit": _edit_any(db, user),
    }


class EventTierIn(BaseModel):
    tier_id: int | None = None


@router.put("/events/{event_id}/dues-tier")
def set_event_tier(event_id: int, payload: EventTierIn, db: DB, user: CurrentUser) -> dict:
    """Which dues tier everyone on this event's teams owes (None: no dues)."""
    access.require_privilege(db, user, "finance.edit")
    ev = db.get(Event, event_id)
    if ev is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such event")
    if payload.tier_id is not None and db.get(DuesTier, payload.tier_id) is None:
        raise HTTPException(422, "Unknown tier")
    old = ev.dues_tier_id
    ev.dues_tier_id = payload.tier_id
    audit.log(db, user.id, "finance", "event_dues_tier", "events", ev.id, {"from": old, "to": payload.tier_id})
    db.commit()
    return {"ok": True}
