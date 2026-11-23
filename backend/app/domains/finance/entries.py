"""Logging money: the only way new money enters the books outside an admin's
correction grid. Whoever logs an entry *is* its holder — the account that took
the dues, paid the supplier, received the sponsor's money or handed cash over.
Nobody picks a holder, so nobody can log money as someone else.

Every write is audited in the bulk grid's own format (same history and recycle
bin as the Advanced sheets), so an entry made here and a correction made there
read as one trail."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domains.audit import service as audit
from app.domains.bulk import service as bulk
from app.domains.bulk.registry import TABLES
from app.domains.events.models import Event, EventCategory, EventTeam
from app.domains.finance import service
from app.domains.finance.models import (
    CashTransfer,
    DuesPayment,
    FinanceOption,
    FinanceParty,
    FinanceSeason,
    FundingLine,
    FundingStatus,
    OptionList,
    SeasonStatus,
    Spending,
)
from app.domains.users.models import User

FROZEN = {SeasonStatus.CLOSED, SeasonStatus.CANCELLED}


def _bad(msg: str, code: int = 422):
    raise HTTPException(code, msg)


# --- lookups ------------------------------------------------------------------
def season_for(db: Session, on: date) -> FinanceSeason:
    """The season a date falls in: the latest dated, open season starting on or
    before it (whose end, if any, is not before it); else the current season."""
    best = None
    for s in service.seasons(db):
        if s.start_date is None or s.status in FROZEN or s.start_date > on:
            continue
        if s.end_date is not None and s.end_date < on:
            continue
        if best is None or s.start_date > best.start_date:
            best = s
    best = best or service.current_season(db)
    if best is None:
        _bad("No finance season is set up yet — ask a finance admin to create one.", 409)
    return best


def _season_open(season: FinanceSeason | None) -> None:
    if season is not None and season.status in FROZEN:
        _bad(f"{season.name} is {season.status}; its books are frozen.", 409)


def _option(db: Session, oid: int | None, list_key: str, label: str, required: bool = False) -> int | None:
    if oid is None:
        if required:
            _bad(f"Pick a {label}.")
        return None
    o = db.get(FinanceOption, oid)
    if o is None or o.list_key != list_key:
        _bad(f"Unknown {label}.")
    return oid


def _party(db: Session, pid: int | None, new_name: str | None) -> int | None:
    """An existing contact, or a new one created on the spot by name."""
    if pid is not None:
        if db.get(FinanceParty, pid) is None:
            _bad("Unknown contact.")
        return pid
    name = (new_name or "").strip()
    if not name:
        return None
    existing = db.scalar(select(FinanceParty).where(FinanceParty.name == name))
    if existing is not None:
        return existing.id
    p = FinanceParty(name=name, is_active=True)
    db.add(p)
    db.flush()
    _audit(db, None, "finance_parties", p, created=True)
    return p.id


# --- audit in the grid's format ----------------------------------------------
def _audit(db: Session, actor_id: int | None, table: str, obj, created: bool = False,
           before: dict | None = None) -> None:
    spec = TABLES[table]
    after = bulk._row_cells(db, spec, obj)
    if created:
        audit.log(db, actor_id, "bulk", "create", table, obj.id, {"row": bulk._editable(spec, after)})
        return
    changes = {
        c.name: [(before or {}).get(c.name, ""), after.get(c.name, "")]
        for c in spec.columns
        if c.name != "id" and (before or {}).get(c.name, "") != after.get(c.name, "")
    }
    if changes:
        audit.log(db, actor_id, "bulk", "update", table, obj.id, {"changes": changes})


# --- money in -----------------------------------------------------------------
def log_dues(db: Session, user: User, *, member_id: int, amount: float, method_id: int | None,
             paid_on: date, note: str | None) -> DuesPayment:
    if db.get(User, member_id) is None:
        _bad("Unknown member.")
    if not amount:
        _bad("Enter an amount.")
    season = season_for(db, paid_on)
    p = DuesPayment(
        season_id=season.id, member_id=member_id, amount=amount, paid_on=paid_on,
        method_id=_option(db, method_id, OptionList.PAYMENT_METHOD, "payment method", required=True),
        holder_id=user.id, note=(note or None),
    )
    db.add(p)
    db.flush()
    _audit(db, user.id, "dues_payments", p, created=True)
    return p


def log_funding(db: Session, user: User, *, amount: float, method_id: int | None, received_on: date,
                funding_id: int | None, party_id: int | None, party_name: str | None,
                source: str | None, type_id: int | None, note: str | None) -> FundingLine:
    """Sponsor / grant / other money received. Either settles an expected
    funding line (`funding_id`) or records a new one already received."""
    method = _option(db, method_id, OptionList.PAYMENT_METHOD, "payment method", required=True)
    if amount is None or amount <= 0:
        _bad("Enter an amount.")
    if funding_id is not None:
        f = db.get(FundingLine, funding_id)
        if f is None:
            _bad("Unknown funding line.", 404)
        if f.received_on is not None:
            _bad("That funding was already received.", 409)
        _season_open(db.get(FinanceSeason, f.season_id))
        before = bulk._row_cells(db, TABLES["funding_lines"], f)
        f.received_on, f.method_id, f.holder_id = received_on, method, user.id
        f.amount, f.status = amount, FundingStatus.SECURED
        if note:
            f.note = note
        db.flush()
        _audit(db, user.id, "funding_lines", f, before=before)
        return f
    pid = _party(db, party_id, party_name)
    label = (source or "").strip() or (db.get(FinanceParty, pid).name if pid else "")
    if not label:
        _bad("Say who the money is from.")
    f = FundingLine(
        season_id=season_for(db, received_on).id, source=label, party_id=pid,
        type_id=_option(db, type_id, OptionList.FUNDING_TYPE, "funding type"),
        amount=amount, status=FundingStatus.SECURED, received_on=received_on,
        method_id=method, holder_id=user.id, note=(note or None),
    )
    db.add(f)
    db.flush()
    _audit(db, user.id, "funding_lines", f, created=True)
    return f


# --- money out ----------------------------------------------------------------
def _check_team(db: Session, event_id: int | None, team_id: int | None) -> None:
    if event_id is not None and db.get(Event, event_id) is None:
        _bad("Unknown event.")
    if team_id is None:
        return
    team = db.get(EventTeam, team_id)
    if team is None or team.deleted_at is not None:
        _bad("Unknown team.")
    team_event = db.scalar(select(EventCategory.event_id).where(EventCategory.id == team.category_id))
    if event_id is None or team_event != event_id:
        _bad("That team isn't part of the chosen event.")


def _check_subcategory(db: Session, category_id: int | None, subcategory_id: int | None) -> None:
    _option(db, category_id, OptionList.CATEGORY, "category")
    _option(db, subcategory_id, OptionList.SUBCATEGORY, "sub-category")


def log_spending(db: Session, user: User, *, item: str, amount: float | None, count: float | None,
                 unit_cost: float | None, method_id: int | None, spent_on: date, event_id: int | None,
                 event_team_id: int | None, category_id: int | None, subcategory_id: int | None,
                 payee_party_id: int | None, payee_name: str | None, receipt: str | None,
                 note: str | None) -> Spending:
    item = (item or "").strip()
    if not item:
        _bad("Say what the money was spent on.")
    count = count if count else 1
    if unit_cost is None:
        unit_cost = (amount or 0) / count
    if not unit_cost or unit_cost <= 0:
        _bad("Enter what it cost.")
    _check_team(db, event_id, event_team_id)
    _check_subcategory(db, category_id, subcategory_id)
    s = Spending(
        season_id=season_for(db, spent_on).id, item=item, count=count, unit_cost=unit_cost,
        method_id=_option(db, method_id, OptionList.PAYMENT_METHOD, "payment method", required=True),
        spent_on=spent_on, event_id=event_id, event_team_id=event_team_id,
        category_id=category_id, subcategory_id=subcategory_id,
        payee_party_id=_party(db, payee_party_id, payee_name),
        receipt=(receipt or None), note=(note or None), holder_id=user.id,
    )
    db.add(s)
    db.flush()
    _audit(db, user.id, "spendings", s, created=True)
    return s


# --- hand-over ------------------------------------------------------------------
def handover(db: Session, user: User, *, to_user_id: int, amount: float, fees: float | None,
             from_method_id: int | None, to_method_id: int | None, on: date,
             note: str | None) -> CashTransfer:
    # handing to yourself is allowed: moving money between methods (cash → bank)
    if to_user_id not in service.cash_holder_ids(db):
        _bad("They can't hold the team's money — pick someone with the cash-holder privilege.")
    if not amount or amount <= 0:
        _bad("Enter an amount.")
    frm = _option(db, from_method_id, OptionList.PAYMENT_METHOD, "payment method", required=True)
    to = _option(db, to_method_id, OptionList.PAYMENT_METHOD, "payment method") or frm
    if to_user_id == user.id and to == frm:
        _bad("Pick another person, or a different method to move it between.")
    t = CashTransfer(
        transferred_on=on, from_user_id=user.id, to_user_id=to_user_id, amount=amount,
        fees=fees or 0, from_method_id=frm, to_method_id=to, note=(note or None),
    )
    db.add(t)
    db.flush()
    _audit(db, user.id, "cash_transfers", t, created=True)
    return t


# --- the ledger -----------------------------------------------------------------
KINDS = {
    "dues": ("dues_payments", DuesPayment),
    "funding": ("funding_lines", FundingLine),
    "spending": ("spendings", Spending),
    "handover": ("cash_transfers", CashTransfer),
}


@dataclass
class _Ctx:
    holders: service.Holders
    options: dict[int, str]
    events: dict[int, str]
    teams: dict[int, str]


def _holder_of(kind: str, obj) -> service.HolderKey | None:
    ctx_key = {
        "dues": lambda o: (o.holder_id, o.received_by_id),
        "spending": lambda o: (o.holder_id, o.paid_by_id),
        "funding": lambda o: (o.holder_id, None),
        "handover": lambda o: (o.from_user_id, o.from_party_id),
    }[kind]
    return ctx_key(obj)


def _entry(kind: str, o, ctx: _Ctx, user_id: int, can_edit_any: bool) -> dict:
    uid, pid = _holder_of(kind, o)
    key = ctx.holders.key(uid, pid)
    holder = ctx.holders.out(key)
    mine = key == ("user", user_id)
    base = {"kind": kind, "id": o.id, "holder": holder, "mine": mine,
            "can_edit": mine or can_edit_any, "note": o.note}
    if kind == "dues":
        return {**base, "date": o.paid_on.isoformat(), "amount": o.amount or 0, "direction": "in",
                "title": f"Dues — {o.member.full_name if o.member else '#' + str(o.member_id)}",
                "member_id": o.member_id, "season_id": o.season_id,
                "method": ctx.options.get(o.method_id), "method_id": o.method_id}
    if kind == "funding":
        return {**base, "date": o.received_on.isoformat() if o.received_on else None,
                "amount": o.amount or 0, "direction": "in", "title": o.source,
                "season_id": o.season_id, "method": ctx.options.get(o.method_id), "method_id": o.method_id,
                "party_id": o.party_id, "type": ctx.options.get(o.type_id)}
    if kind == "spending":
        return {**base, "date": o.spent_on.isoformat() if o.spent_on else None, "amount": o.net,
                "direction": "out", "title": o.item, "season_id": o.season_id,
                "method": ctx.options.get(o.method_id), "method_id": o.method_id,
                "event_id": o.event_id, "event": ctx.events.get(o.event_id),
                "event_team_id": o.event_team_id, "team": ctx.teams.get(o.event_team_id),
                "category": ctx.options.get(o.category_id), "category_id": o.category_id,
                "subcategory_id": o.subcategory_id, "count": o.count, "unit_cost": o.unit_cost,
                "receipt": o.receipt, "payee_party_id": o.payee_party_id,
                "payee": ctx.holders.parties[o.payee_party_id].name
                if o.payee_party_id in ctx.holders.parties else None}
    to = ctx.holders.out(ctx.holders.key(o.to_user_id, o.to_party_id))
    return {**base, "date": o.transferred_on.isoformat() if o.transferred_on else None,
            "amount": o.amount or 0, "fees": o.fees or 0, "direction": "move",
            "title": f"Handed to {to['name']}" if holder and to else
                     (f"Opening balance — {to['name']}" if to else "Transfer"),
            "to": to, "season_id": None, "method": ctx.options.get(o.from_method_id),
            "method_id": o.from_method_id, "to_method": ctx.options.get(o.to_method_id)}


def ledger(db: Session, user: User, *, season_id: int | None, kind: str | None,
           holder_id: int | None, mine: bool, can_edit_any: bool, limit: int = 300) -> dict:
    ctx = _Ctx(
        holders=service.Holders(db),
        options={o.id: o.value for o in db.scalars(select(FinanceOption))},
        events={e.id: e.name for e in db.scalars(select(Event))},
        teams={t.id: t.path_name for t in db.scalars(select(EventTeam))},
    )
    out: list[dict] = []
    for k, (_table, model) in KINDS.items():
        if kind and k != kind:
            continue
        q = select(model)
        if k == "funding":
            q = q.where(FundingLine.received_on.is_not(None))
        if season_id is not None and hasattr(model, "season_id"):
            q = q.where(model.season_id == season_id)
        for o in db.scalars(q):
            e = _entry(k, o, ctx, user.id, can_edit_any)
            involved = {e["holder"]["id"] if e["holder"] and not e["holder"]["legacy"] else None}
            if k == "handover" and e.get("to") and not e["to"]["legacy"]:
                involved.add(e["to"]["id"])
            if mine and user.id not in involved:
                continue
            if holder_id is not None and holder_id not in involved:
                continue
            out.append(e)
    out.sort(key=lambda e: (e["date"] or "", e["kind"], e["id"]), reverse=True)
    return {"entries": out[:limit], "total": len(out)}


# --- corrections ------------------------------------------------------------------
EDITABLE = {
    "dues": {"amount", "method_id", "paid_on", "note", "member_id"},
    "funding": {"amount", "method_id", "received_on", "note", "source", "party_id", "type_id"},
    "spending": {"item", "count", "unit_cost", "method_id", "spent_on", "event_id", "event_team_id",
                 "category_id", "subcategory_id", "payee_party_id", "receipt", "note"},
    "handover": {"amount", "fees", "from_method_id", "to_method_id", "transferred_on", "note", "to_user_id"},
}


def _load(db: Session, kind: str, entry_id: int):
    if kind not in KINDS:
        _bad("Unknown entry kind.", 404)
    obj = db.get(KINDS[kind][1], entry_id)
    if obj is None or (kind == "funding" and obj.received_on is None):
        _bad("No such entry.", 404)
    return obj


def _may_touch(db: Session, user: User, kind: str, obj, can_edit_any: bool) -> None:
    uid, pid = _holder_of(kind, obj)
    if service.Holders(db).key(uid, pid) != ("user", user.id) and not can_edit_any:
        _bad("Only the person who logged this (or a finance admin) can change it.", 403)
    _season_open(db.get(FinanceSeason, obj.season_id) if getattr(obj, "season_id", None) else None)


def update_entry(db: Session, user: User, kind: str, entry_id: int, fields: dict, can_edit_any: bool):
    obj = _load(db, kind, entry_id)
    _may_touch(db, user, kind, obj, can_edit_any)
    unknown = set(fields) - EDITABLE[kind]
    if unknown:
        _bad(f"Can't change {', '.join(sorted(unknown))} here.")
    table = KINDS[kind][0]
    before = bulk._row_cells(db, TABLES[table], obj)
    for f in ("method_id", "from_method_id", "to_method_id"):
        if f in fields:
            _option(db, fields[f], OptionList.PAYMENT_METHOD, "payment method", required=f != "to_method_id")
    if kind == "spending":
        _check_team(db, fields.get("event_id", obj.event_id), fields.get("event_team_id", obj.event_team_id))
        _check_subcategory(db, fields.get("category_id"), fields.get("subcategory_id"))
    if kind == "handover" and "to_user_id" in fields and fields["to_user_id"] not in service.cash_holder_ids(db):
        _bad("They can't hold the team's money.")
    if kind == "dues" and "member_id" in fields and db.get(User, fields["member_id"]) is None:
        _bad("Unknown member.")
    for k, v in fields.items():
        setattr(obj, k, v)
    # a date moved into another season moves the entry with it
    for date_attr in ("paid_on", "spent_on", "received_on"):
        if date_attr in fields and fields[date_attr] is not None and hasattr(obj, "season_id"):
            obj.season_id = season_for(db, fields[date_attr]).id
    db.flush()
    _audit(db, user.id, table, obj, before=before)
    return obj


def delete_entry(db: Session, user: User, kind: str, entry_id: int, can_edit_any: bool) -> None:
    obj = _load(db, kind, entry_id)
    _may_touch(db, user, kind, obj, can_edit_any)
    result = bulk.apply(db, TABLES[KINDS[kind][0]], [], [entry_id], user.id)
    if not result["ok"]:
        _bad(result["errors"][0]["message"] if result["errors"] else "Couldn't delete it.", 409)
