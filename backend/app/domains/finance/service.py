"""The finance books' derived figures — everything the old spreadsheet computed
with formulas: dues maturity / fees / balances and the monthly payment grid,
the season projection, cash balances per holder and method, and the dashboard
roll-ups. Pure reads; nothing here writes."""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domains.events.models import Event
from app.domains.finance.models import (
    BudgetLine,
    CashTransfer,
    DuesDiscount,
    DuesEnrollment,
    DuesPayment,
    DuesTier,
    EnrollmentStatus,
    FinanceOption,
    FinanceParty,
    FinanceSeason,
    FundingLine,
    FundingStatus,
    OptionList,
    Payable,
    PayableStatus,
    SeasonStatus,
    Spending,
)

# How many monthly columns the dues grid shows when a season has no end date.
DEFAULT_SEASON_MONTHS = 10


# --- seasons -----------------------------------------------------------------
def seasons(db: Session) -> list[FinanceSeason]:
    return list(db.scalars(select(FinanceSeason).order_by(FinanceSeason.sort_order, FinanceSeason.id)))


def current_season(db: Session) -> FinanceSeason | None:
    """The season the books default to: the first active one that has a start
    date (a real season, not a team-wide bucket), else the first season."""
    all_seasons = seasons(db)
    for s in all_seasons:
        if s.status == SeasonStatus.ACTIVE and s.start_date is not None:
            return s
    return all_seasons[0] if all_seasons else None


def _months(start: date, count: int) -> list[date]:
    out, y, m = [], start.year, start.month
    for _ in range(count):
        out.append(date(y, m, 1))
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


def season_months(season: FinanceSeason) -> list[date]:
    """First-of-month dates the dues grid spans for a season."""
    if season.start_date is None:
        return []
    start = season.start_date.replace(day=1)
    if season.end_date is not None and season.end_date >= start:
        count = (season.end_date.year - start.year) * 12 + season.end_date.month - start.month + 1
    else:
        count = DEFAULT_SEASON_MONTHS
    return _months(start, count)


# --- dues --------------------------------------------------------------------
def _full_years(start: date, end: date) -> int:
    """Whole years from start to end (spreadsheet DATEDIF "Y")."""
    years = end.year - start.year
    if (end.month, end.day) < (start.month, start.day):
        years -= 1
    return max(years, 0)


def maturity(enrollment: DuesEnrollment, season: FinanceSeason) -> int:
    """Years with the team at the season start: the override if set, else
    counted from the member's first registration."""
    if enrollment.maturity_override is not None:
        return enrollment.maturity_override
    joined = enrollment.member.joined_at if enrollment.member is not None else None
    if joined is None:
        return 0
    return _full_years(joined.date(), season.start_date or date.today())


def discount_for(years: int, discounts: list[DuesDiscount]) -> float:
    best = 0.0
    for d in sorted(discounts, key=lambda d: d.min_years):
        if years >= d.min_years:
            best = d.discount
    return best


def dues_ledger(db: Session, season: FinanceSeason) -> dict:
    """The season's dues roster: every enrolment with its maturity, discount,
    monthly fee, what it paid each month, and what it still owes — plus the
    projection by segment and the totals."""
    discounts = list(db.scalars(select(DuesDiscount).where(DuesDiscount.season_id == season.id)))
    tiers = list(db.scalars(select(DuesTier).where(DuesTier.season_id == season.id).order_by(DuesTier.sort_order, DuesTier.id)))
    enrollments = list(db.scalars(select(DuesEnrollment).where(DuesEnrollment.season_id == season.id)))
    payments = list(db.scalars(select(DuesPayment).where(DuesPayment.season_id == season.id)))
    months = season_months(season)
    month_keys = [m.strftime("%Y-%m") for m in months]

    paid_by_member: dict[int, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    paid_total: dict[int, float] = defaultdict(float)
    for p in payments:
        paid_total[p.member_id] += p.amount or 0
        paid_by_member[p.member_id][p.paid_on.strftime("%Y-%m")] += p.amount or 0

    rows = []
    segments: dict[tuple[int, float], dict] = {}
    for e in enrollments:
        years = maturity(e, season)
        disc = discount_for(years, discounts)
        tier = e.tier
        fee = round((tier.monthly_fee or 0) * (1 - disc), 2)
        active = e.status == EnrollmentStatus.ACTIVE
        expected_full = fee * (tier.months or 0) + (tier.one_time_fee or 0)
        paid = paid_total.get(e.member_id, 0.0)
        expected = expected_full if active else paid
        member = e.member
        rows.append({
            "enrollment_id": e.id,
            "member_id": e.member_id,
            "name": member.display_name if member else "",
            "mtr_id": member.mtr_id if member else None,
            "tier": tier.name,
            "joined_at": member.joined_at.date().isoformat() if member and member.joined_at else None,
            "maturity": years,
            "maturity_overridden": e.maturity_override is not None,
            "discount": disc,
            "monthly_fee": fee,
            "status": e.status,
            "months_due": tier.months or 0,
            "monthly": {k: paid_by_member[e.member_id].get(k, 0.0) for k in month_keys},
            "paid": paid,
            "expected": expected,
            "balance": expected - paid,
            "note": e.note,
        })
        if active:
            seg = segments.setdefault((tier.id, disc), {
                "tier": tier.name,
                "discount": disc,
                "base": tier.monthly_fee or 0,
                "monthly_fee": fee,
                "months": tier.months or 0,
                "one_time_fee": tier.one_time_fee or 0,
                "members": 0,
                "projected": 0.0,
                "_order": (tiers.index(tier) if tier in tiers else 99, disc),
            })
            seg["members"] += 1
            seg["projected"] += expected_full

    rows.sort(key=lambda r: (r["status"] != EnrollmentStatus.ACTIVE, r["name"].lower()))
    projection = sorted(segments.values(), key=lambda s: s.pop("_order"))
    collected = sum(p.amount or 0 for p in payments)
    return {
        "season": _season_out(season),
        "months": month_keys,
        "rows": rows,
        "projection": projection,
        "totals": {
            "members": len(rows),
            "active": sum(1 for r in rows if r["status"] == EnrollmentStatus.ACTIVE),
            "projected": sum(s["projected"] for s in projection),
            "collected": collected,
            "expected": sum(r["expected"] for r in rows),
            "balance": sum(r["balance"] for r in rows),
            # payments logged for members not enrolled this season
            "unenrolled_paid": collected - sum(r["paid"] for r in rows),
            "by_month": {k: sum(r["monthly"][k] for r in rows) for k in month_keys},
        },
    }


# --- cash --------------------------------------------------------------------
def cash_balances(db: Session) -> dict:
    """Money each holder has, per payment method: transfers in − transfers out
    − transfer fees − spendings they paid + dues they received."""
    methods = list(db.scalars(
        select(FinanceOption)
        .where(FinanceOption.list_key == OptionList.PAYMENT_METHOD)
        .order_by(FinanceOption.sort_order, FinanceOption.id)
    ))
    parties = {p.id: p for p in db.scalars(select(FinanceParty))}
    bal: dict[int, dict[int | None, float]] = defaultdict(lambda: defaultdict(float))

    for t in db.scalars(select(CashTransfer)):
        if t.to_party_id is not None:
            bal[t.to_party_id][t.to_method_id] += t.amount or 0
        if t.from_party_id is not None:
            bal[t.from_party_id][t.from_method_id] -= (t.amount or 0) + (t.fees or 0)
    for s in db.scalars(select(Spending).where(Spending.paid_by_id.is_not(None))):
        bal[s.paid_by_id][s.method_id] -= s.net
    for p in db.scalars(select(DuesPayment).where(DuesPayment.received_by_id.is_not(None))):
        bal[p.received_by_id][p.method_id] += p.amount or 0

    holder_type_names = {"cfo", "cash holder"}
    holder_ids = set(bal) | {
        pid for pid, p in parties.items()
        if p.is_active and p.type is not None and p.type.value.strip().lower() in holder_type_names
    }
    columns = [{"id": m.id, "name": m.value} for m in methods]
    has_unassigned = any(None in by_method for by_method in bal.values())
    if has_unassigned:
        columns.append({"id": None, "name": "Unspecified"})

    rows = []
    for pid in sorted(holder_ids, key=lambda i: parties[i].name.lower() if i in parties else ""):
        by_method = bal.get(pid, {})
        cells = {str(c["id"]): by_method.get(c["id"], 0.0) for c in columns}
        rows.append({
            "party_id": pid,
            "name": parties[pid].name if pid in parties else f"#{pid}",
            "cells": cells,
            "total": sum(by_method.values()),
        })
    totals = {str(c["id"]): sum(r["cells"][str(c["id"])] for r in rows) for c in columns}
    return {"methods": columns, "rows": rows, "totals": totals, "total": sum(r["total"] for r in rows)}


# --- dashboard -----------------------------------------------------------------
def _season_out(s: FinanceSeason) -> dict:
    return {
        "id": s.id, "name": s.name, "status": s.status,
        "start_date": s.start_date.isoformat() if s.start_date else None,
        "end_date": s.end_date.isoformat() if s.end_date else None,
        "usd_rate": s.usd_rate,
    }


def _option_names(db: Session) -> dict[int, str]:
    return {o.id: o.value for o in db.scalars(select(FinanceOption))}


def dashboard(db: Session, season_id: int | None) -> dict:
    """The finance overview. `season_id` narrows every season-scoped figure to
    one season; None rolls up every season. Cash on hand is always global
    (money sits with a holder regardless of which season it's earmarked for)."""
    names = _option_names(db)
    all_seasons = seasons(db)
    scope = [s for s in all_seasons if season_id is None or s.id == season_id]
    scope_ids = {s.id for s in scope}

    budget = [b for b in db.scalars(select(BudgetLine)) if b.season_id in scope_ids]
    spend = [s for s in db.scalars(select(Spending)) if s.season_id in scope_ids]
    funding = [f for f in db.scalars(select(FundingLine)) if f.season_id in scope_ids]
    payments = [p for p in db.scalars(select(DuesPayment)) if p.season_id in scope_ids]
    payables = [
        p for p in db.scalars(select(Payable))
        if season_id is None or p.season_id == season_id
    ]

    projected_dues = sum(dues_ledger(db, s)["totals"]["projected"] for s in scope)
    plan_needed = sum(b.needed_cost for b in budget)
    plan_fmv = sum(b.fmv for b in budget)
    spent = sum(s.net for s in spend)
    collected = sum(p.amount or 0 for p in payments)
    funding_secured = sum(f.amount or 0 for f in funding if f.status == FundingStatus.SECURED)
    funding_expected = sum(f.amount or 0 for f in funding if f.status == FundingStatus.EXPECTED)
    owed = sum(p.amount or 0 for p in payables if p.status == PayableStatus.OWED)
    cash = cash_balances(db)

    per_season = []
    for s in scope:
        s_needed = sum(b.needed_cost for b in budget if b.season_id == s.id)
        s_spent = sum(x.net for x in spend if x.season_id == s.id)
        per_season.append({
            "season_id": s.id,
            "season": s.name,
            "fmv": sum(b.fmv for b in budget if b.season_id == s.id),
            "needed": s_needed,
            "spent": s_spent,
            "left": s_needed - s_spent,
            "status": _budget_status(s_needed, s_spent),
        })

    def group(rows, key, value):
        out: dict[str, float] = defaultdict(float)
        for r in rows:
            out[names.get(key(r), "Unassigned") if key(r) is not None else "Unassigned"] += value(r)
        return out

    sub_fmv = group(budget, lambda b: b.subsystem_id, lambda b: b.fmv)
    sub_needed = group(budget, lambda b: b.subsystem_id, lambda b: b.needed_cost)
    cat_needed = group(budget, lambda b: b.category_id, lambda b: b.needed_cost)
    cat_spent = group(spend, lambda s: s.category_id, lambda s: s.net)

    # keep pick-list order, then anything unassigned
    def ordered(list_key: str, keys: set[str]) -> list[str]:
        listed = [o.value for o in db.scalars(
            select(FinanceOption).where(FinanceOption.list_key == list_key)
            .order_by(FinanceOption.sort_order, FinanceOption.id)
        )]
        return [k for k in listed if k in keys] + sorted(k for k in keys if k not in listed)

    by_subsystem = [
        {"name": k, "fmv": sub_fmv.get(k, 0.0), "needed": sub_needed.get(k, 0.0)}
        for k in ordered(OptionList.SUBSYSTEM, set(sub_fmv) | set(sub_needed))
    ]
    by_category = [
        {"name": k, "needed": cat_needed.get(k, 0.0), "spent": cat_spent.get(k, 0.0)}
        for k in ordered(OptionList.CATEGORY, set(cat_needed) | set(cat_spent))
    ]

    monthly: dict[str, dict[str, float]] = defaultdict(lambda: {"collected": 0.0, "spent": 0.0})
    for p in payments:
        monthly[p.paid_on.strftime("%Y-%m")]["collected"] += p.amount or 0
    for s in spend:
        if s.spent_on is not None:
            monthly[s.spent_on.strftime("%Y-%m")]["spent"] += s.net

    event_names = {e.id: e.name for e in db.scalars(select(Event))}
    by_event: dict[str, dict[str, float]] = defaultdict(lambda: {"needed": 0.0, "spent": 0.0})
    for b in budget:
        by_event[event_names.get(b.event_id, "Team-wide")]["needed"] += b.needed_cost
    for s in spend:
        by_event[event_names.get(s.event_id, "Team-wide")]["spent"] += s.net

    funding_pipeline = sum(f.amount or 0 for f in funding) + projected_dues
    return {
        "seasons": [_season_out(s) for s in all_seasons],
        "season_id": season_id,
        "kpis": {
            "plan_needed": plan_needed,
            "plan_fmv": plan_fmv,
            "spent": spent,
            "dues_collected": collected,
            "funding_secured": funding_secured,
            "funding_expected": funding_expected,
            "cash_on_hand": cash["total"],
            "projected_dues": projected_dues,
            "dues_coverage": (projected_dues / plan_needed) if plan_needed else 0.0,
            "gap": plan_needed - funding_pipeline,
            "owed": owed,
        },
        "per_season": per_season,
        "by_subsystem": by_subsystem,
        "by_category": by_category,
        "by_event": [{"name": k, **v} for k, v in sorted(by_event.items(), key=lambda kv: -kv[1]["needed"])],
        "monthly": [{"month": k, **v} for k, v in sorted(monthly.items())],
        "funding": [
            {"source": f.source, "type": names.get(f.type_id) if f.type_id else None,
             "amount": f.amount, "status": f.status, "season_id": f.season_id}
            for f in funding
        ],
        "cash": cash,
    }


def _budget_status(needed: float, spent: float) -> str:
    if needed == 0 and spent == 0:
        return "empty"
    if spent > needed:
        return "over"
    if spent == 0:
        return "not started"
    return "on track"


def event_money(db: Session, event_id: int) -> dict:
    """What the books hold for one event: planned (from budget lines) and spent
    (from spendings). `has_books` is false when the event has no lines, in which
    case the event's own recorded totals are the only figures there are."""
    lines = list(db.scalars(select(BudgetLine).where(BudgetLine.event_id == event_id)))
    spend = list(db.scalars(select(Spending).where(Spending.event_id == event_id)))
    return {
        "has_books": bool(lines or spend),
        "planned_fmv": sum(b.fmv for b in lines),
        "planned_needed": sum(b.needed_cost for b in lines),
        "spent": sum(s.net for s in spend),
        "budget_lines": len(lines),
    }
