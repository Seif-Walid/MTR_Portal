"""The finance books: derived figures (budget FMV/needed, dues maturity, fees,
balances, cash), the dashboard roll-up, privilege gating, and editing through
the bulk grid (filtered pick-lists, computed read-only columns, delete guards)."""

from datetime import date, datetime, timezone

import pytest

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
    Spending,
)
from app.domains.users.models import MemberProfile


@pytest.fixture()
def books(db_session):
    db = db_session
    season = FinanceSeason(name="S4", status="active", start_date=date(2026, 9, 1), usd_rate=50)
    db.add(season)
    db.flush()
    cash = FinanceOption(list_key="payment_method", value="Cash", sort_order=0)
    insta = FinanceOption(list_key="payment_method", value="Instapay", sort_order=1)
    hw = FinanceOption(list_key="category", value="Hardware", sort_order=0)
    mech = FinanceOption(list_key="subsystem", value="Mechanical", sort_order=0)
    holder_type = FinanceOption(list_key="party_type", value="Cash Holder", sort_order=0)
    db.add_all([cash, insta, hw, mech, holder_type])
    db.flush()
    osama = FinanceParty(name="Osama", type_id=holder_type.id)
    db.add(osama)
    active = DuesTier(season_id=season.id, name="Active", monthly_fee=600, months=7)
    db.add(active)
    db.add_all([
        DuesDiscount(season_id=season.id, min_years=0, discount=0),
        DuesDiscount(season_id=season.id, min_years=1, discount=0.5),
        DuesDiscount(season_id=season.id, min_years=2, discount=0.9),
    ])
    veteran = MemberProfile(full_name="Veteran", mtr_id="MTR-001",
                            joined_at=datetime(2024, 1, 1, tzinfo=timezone.utc))
    rookie = MemberProfile(full_name="Rookie", mtr_id="MTR-011",
                           joined_at=datetime(2026, 7, 1, tzinfo=timezone.utc))
    quitter = MemberProfile(full_name="Quitter", mtr_id="MTR-012")
    db.add_all([veteran, rookie, quitter])
    db.flush()
    db.add_all([
        DuesEnrollment(season_id=season.id, member_id=veteran.id, tier_id=active.id),
        DuesEnrollment(season_id=season.id, member_id=rookie.id, tier_id=active.id),
        DuesEnrollment(season_id=season.id, member_id=quitter.id, tier_id=active.id,
                       status=EnrollmentStatus.WITHDRAWN),
        DuesPayment(season_id=season.id, member_id=rookie.id, paid_on=date(2026, 9, 3), amount=600,
                    method_id=cash.id, received_by_id=osama.id),
        DuesPayment(season_id=season.id, member_id=quitter.id, paid_on=date(2026, 9, 5), amount=600),
        # USD price converts at the season rate; 2 required + 1 spare, 1 in stock
        BudgetLine(season_id=season.id, item="Thruster", currency="USD", unit_price=100,
                   required_qty=2, spare_qty=1, in_stock_qty=1, subsystem_id=mech.id, category_id=hw.id),
        BudgetLine(season_id=season.id, item="Bolts", unit_price=10, required_qty=5, category_id=hw.id),
        Spending(season_id=season.id, item="Bolts", count=5, unit_cost=12, category_id=hw.id,
                 spent_on=date(2026, 9, 10), method_id=cash.id, paid_by_id=osama.id),
        FundingLine(season_id=season.id, source="Carry-over", amount=1000, status=FundingStatus.SECURED),
        CashTransfer(amount=2000, to_party_id=osama.id, to_method_id=cash.id),  # opening balance
    ])
    db.commit()
    return {"season": season, "osama": osama, "veteran": veteran, "rookie": rookie, "hw": hw, "cash": cash}


def _grant(db, login_name, org, *privs):
    import json
    from app.domains.access.models import AccessLevel
    level = db.get(AccessLevel, org[login_name].access_level_id)
    level.privileges = json.dumps(sorted(set(json.loads(level.privileges)) | set(privs)))
    db.commit()


def test_budget_line_math(books, db_session):
    thruster = db_session.query(BudgetLine).filter_by(item="Thruster").one()
    assert thruster.unit_price_egp == 5000
    assert thruster.total_qty == 3 and thruster.needed_qty == 2
    assert thruster.fmv == 15000 and thruster.needed_cost == 10000


def test_dues_ledger(login, org, books):
    body = login("admin").get("/api/finance/dues").json()
    rows = {r["name"]: r for r in body["rows"]}
    assert rows["Veteran"]["maturity"] == 2 and rows["Veteran"]["monthly_fee"] == 60
    assert rows["Rookie"]["maturity"] == 0 and rows["Rookie"]["expected"] == 4200
    assert rows["Rookie"]["monthly"]["2026-09"] == 600 and rows["Rookie"]["balance"] == 3600
    # withdrawn: stays on record, owes nothing beyond what they paid
    assert rows["Quitter"]["status"] == "withdrawn" and rows["Quitter"]["balance"] == 0
    assert body["months"][0] == "2026-09" and len(body["months"]) == 10
    assert body["totals"]["projected"] == 420 + 4200  # active members only
    assert body["totals"]["collected"] == 1200


def test_dashboard_rollup(login, org, books):
    k = login("admin").get("/api/finance/dashboard").json()["kpis"]
    assert k["plan_needed"] == 10000 + 50 and k["plan_fmv"] == 15000 + 50
    assert k["spent"] == 60 and k["dues_collected"] == 1200 and k["funding_secured"] == 1000
    # gap = needed - (funding lines + projected dues)
    assert k["gap"] == 10050 - (1000 + 4620)
    # cash: opening 2000 + dues received 600 - spending 60
    assert k["cash_on_hand"] == 2540


def test_cash_matrix(login, org, books):
    body = login("admin").get("/api/finance/cash").json()
    osama = next(r for r in body["rows"] if r["name"] == "Osama")
    assert osama["cells"][str(books["cash"].id)] == 2540 and osama["total"] == 2540


def test_finance_is_gated(login, org, books, db_session):
    assert login("ceo").get("/api/finance/dashboard").status_code == 403
    assert login("ceo").get("/api/bulk/budget_lines").status_code == 403
    _grant(db_session, "ceo", org, "finance.view")
    assert login("ceo").get("/api/finance/dashboard").status_code == 200
    assert login("ceo").get("/api/bulk/budget_lines").status_code == 403  # editing needs finance.edit


def test_grid_computed_columns_and_filtered_picklist(login, org, books):
    admin = login("admin")
    body = admin.get("/api/bulk/budget_lines").json()
    thruster = next(r for r in body["rows"] if r["item"] == "Thruster")
    assert thruster["fmv"] == "15000" and thruster["needed_cost"] == "10000"
    assert {c["name"]: c["editable"] for c in body["columns"]}["fmv"] is False
    # the category dropdown only offers category values, not other pick-lists
    assert [o["label"] for o in body["options"]["category_id"]] == ["Hardware"]

    # a value from another pick-list doesn't resolve as a category
    r = admin.post("/api/bulk/budget_lines", json={"rows": [{
        "id": "", "season_id": str(books["season"].id), "item": "X", "category_id": str(books["cash"].id),
    }]}).json()
    assert not r["ok"] and r["errors"][0]["column"] == "category_id"


def test_picklist_grid_scoped_to_its_list(login, org, books):
    admin = login("admin")
    rows = admin.get("/api/bulk/options_payment_method").json()["rows"]
    assert [r["value"] for r in rows] == ["Cash", "Instapay"]
    r = admin.post("/api/bulk/options_payment_method", json={"rows": [{"id": "", "value": "Fawry"}]}).json()
    assert r["ok"], r
    rows = admin.get("/api/bulk/options_payment_method").json()["rows"]
    assert "Fawry" in [r["value"] for r in rows]
    # ids from another list are not editable through this grid
    r = admin.post("/api/bulk/options_payment_method", json={"rows": [{"id": str(books["hw"].id), "value": "Y"}]}).json()
    assert not r["ok"]


def test_option_in_use_cannot_be_deleted(login, org, books):
    r = login("admin").post("/api/bulk/options_category", json={"deletes": [books["hw"].id]}).json()
    assert not r["ok"] and "still used" in r["errors"][0]["message"]


def test_event_money(login, org, books, db_session):
    from app.domains.events.models import Event
    ev = Event(name="MATE ROV 2027", code="ROV27")
    db_session.add(ev)
    db_session.flush()
    for b in db_session.query(BudgetLine):
        b.event_id = ev.id
    db_session.commit()
    body = login("admin").get(f"/api/finance/events/{ev.id}").json()
    assert body["has_books"] and body["planned_needed"] == 10050 and body["spent"] == 0
