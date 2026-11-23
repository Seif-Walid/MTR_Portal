"""Logging money as the signed-in holder, the derived dues roster, and the
legacy-holder resolution that replaced the spreadsheet's party list."""

import json
from datetime import date

import pytest

from app.domains.access.models import AccessLevel
from app.domains.events.models import Event, EventCategory, EventTeam, EventTeamMember
from app.domains.finance.models import (
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


def _grant(db, org, who, *privs):
    level = db.get(AccessLevel, org[who].access_level_id)
    level.privileges = json.dumps(sorted(set(json.loads(level.privileges)) | set(privs)))
    db.commit()


@pytest.fixture()
def fin(db_session, org):
    db = db_session
    season = FinanceSeason(name="S4", status="active", start_date=date(2026, 9, 1))
    db.add(season)
    db.flush()
    cash = FinanceOption(list_key="payment_method", value="Cash", sort_order=0)
    bank = FinanceOption(list_key="payment_method", value="Bank", sort_order=1)
    hw = FinanceOption(list_key="category", value="Hardware")
    db.add_all([cash, bank, hw])
    active = DuesTier(season_id=season.id, name="Active", monthly_fee=600, months=7)
    member = DuesTier(season_id=season.id, name="Member", monthly_fee=200, months=7)
    db.add_all([active, member])
    db.flush()
    rov = Event(name="ROV27", dues_tier_id=active.id)
    gt = Event(name="GT S4", dues_tier_id=member.id)
    other = Event(name="Other")
    db.add_all([rov, gt, other])
    db.flush()
    teams = {}
    for ev in (rov, gt, other):
        cat = EventCategory(event_id=ev.id, name="Main")
        db.add(cat)
        db.flush()
        t = EventTeam(category_id=cat.id, name=f"{ev.name} team")
        db.add(t)
        db.flush()
        teams[ev.name] = t
    db.add_all([
        EventTeamMember(team_id=teams["ROV27"].id, user_id=org["student"].id),
        EventTeamMember(team_id=teams["GT S4"].id, user_id=org["student"].id),  # both: dearest wins
        EventTeamMember(team_id=teams["GT S4"].id, user_id=org["comp_member"].id),
        EventTeamMember(team_id=teams["Other"].id, user_id=org["sw_emp"].id),  # no tier: owes nothing
    ])
    db.commit()
    # cfo holds the money; ceo can only look
    _grant(db, org, "cfo", "finance.view", "finance.handle_cash")
    _grant(db, org, "ceo", "finance.view")
    return {"season": season, "cash": cash, "bank": bank, "hw": hw, "active": active, "member": member,
            "rov": rov, "gt": gt, "other": other, "teams": teams}


def test_roster_derived_from_event_teams(login, org, fin):
    rows = {r["member_id"]: r for r in login("admin").get("/api/finance/dues").json()["rows"]}
    assert rows[org["student"].id]["tier"] == "Active"  # on ROV27 and GT: the dearer tier
    assert sorted(rows[org["student"].id]["events"]) == ["GT S4", "ROV27"]
    assert rows[org["comp_member"].id]["tier"] == "Member" and rows[org["comp_member"].id]["source"] == "team"
    assert org["sw_emp"].id not in rows


def test_exceptions_override_the_derived_roster(login, org, fin, db_session):
    db_session.add_all([
        DuesEnrollment(season_id=fin["season"].id, member_id=org["comp_member"].id,
                       status=EnrollmentStatus.WITHDRAWN),
        DuesEnrollment(season_id=fin["season"].id, member_id=org["student"].id, tier_id=fin["member"].id),
        DuesEnrollment(season_id=fin["season"].id, member_id=org["mech_emp"].id, tier_id=fin["member"].id),
    ])
    db_session.commit()
    rows = {r["member_id"]: r for r in login("admin").get("/api/finance/dues").json()["rows"]}
    assert rows[org["comp_member"].id]["status"] == "withdrawn" and rows[org["comp_member"].id]["balance"] == 0
    assert rows[org["student"].id]["tier"] == "Member" and rows[org["student"].id]["tier_overridden"]
    assert rows[org["mech_emp"].id]["source"] == "manual" and rows[org["mech_emp"].id]["expected"] == 1400


def test_dues_logged_by_holder_is_blamed_on_them(login, org, fin, db_session):
    cfo = login("cfo")
    r = cfo.post("/api/finance/money-in/dues", json={
        "member_id": org["student"].id, "amount": 600, "method_id": fin["cash"].id,
        # a client can't pick the holder: unknown fields are ignored, holder is the session
        "holder_id": org["admin"].id, "received_by_id": 1,
    })
    assert r.status_code == 200, r.text
    p = db_session.get(DuesPayment, r.json()["id"])
    assert p.holder_id == org["cfo"].id and p.season_id == fin["season"].id and p.paid_on == date.today()
    mine = cfo.get("/api/finance/my-cash").json()
    assert mine["total"] == 600
    assert next(m for m in mine["methods"] if m["id"] == fin["cash"].id)["amount"] == 600


def test_logging_money_needs_the_cash_privilege(login, org, fin):
    ceo = login("ceo")
    assert ceo.post("/api/finance/money-in/dues", json={
        "member_id": org["student"].id, "amount": 600, "method_id": fin["cash"].id,
    }).status_code == 403
    assert ceo.get("/api/finance/ledger").status_code == 200  # but may look
    assert login("student").get("/api/finance/ledger").status_code == 403


def test_spending_checks_team_belongs_to_event(login, org, fin):
    cfo = login("cfo")
    bad = cfo.post("/api/finance/money-out", json={
        "item": "Thruster", "amount": 500, "method_id": fin["cash"].id,
        "event_id": fin["rov"].id, "event_team_id": fin["teams"]["GT S4"].id,
    })
    assert bad.status_code == 422
    ok = cfo.post("/api/finance/money-out", json={
        "item": "Thruster", "count": 2, "unit_cost": 250, "method_id": fin["cash"].id,
        "event_id": fin["rov"].id, "event_team_id": fin["teams"]["ROV27"].id, "category_id": fin["hw"].id,
        "payee_name": "Makers",
    })
    assert ok.status_code == 200, ok.text
    assert login("cfo").get("/api/finance/my-cash").json()["total"] == -500
    entries = login("cfo").get("/api/finance/ledger").json()["entries"]
    e = next(x for x in entries if x["kind"] == "spending")
    assert e["amount"] == 500 and e["payee"] == "Makers" and e["holder"]["id"] == org["cfo"].id and e["mine"]


def test_received_funding_counts_in_cash(login, org, fin, db_session):
    planned = FundingLine(season_id=fin["season"].id, source="Sponsor X", amount=5000,
                          status=FundingStatus.EXPECTED)
    db_session.add(planned)
    db_session.commit()
    cfo = login("cfo")
    r = cfo.post("/api/finance/money-in/funding", json={
        "funding_id": planned.id, "amount": 4000, "method_id": fin["bank"].id})
    assert r.status_code == 200, r.text
    db_session.refresh(planned)
    assert planned.holder_id == org["cfo"].id and planned.status == "secured" and planned.amount == 4000
    cash = login("admin").get("/api/finance/cash").json()
    row = next(x for x in cash["rows"] if x["user_id"] == org["cfo"].id)
    assert row["cells"][str(fin["bank"].id)] == 4000


def test_handover_only_to_holders(login, org, fin):
    cfo = login("cfo")
    cfo.post("/api/finance/money-in/dues", json={
        "member_id": org["student"].id, "amount": 1000, "method_id": fin["cash"].id})
    assert cfo.post("/api/finance/handover", json={
        "to_user_id": org["student"].id, "amount": 100, "from_method_id": fin["cash"].id,
    }).status_code == 422
    r = cfo.post("/api/finance/handover", json={
        "to_user_id": org["admin"].id, "amount": 300, "fees": 5, "from_method_id": fin["cash"].id,
        "to_method_id": fin["bank"].id})
    assert r.status_code == 200, r.text
    assert cfo.get("/api/finance/my-cash").json()["total"] == 1000 - 305
    assert login("admin").get("/api/finance/my-cash").json()["total"] == 300


def test_only_the_holder_or_finance_admin_can_correct(login, org, fin, db_session):
    cfo = login("cfo")
    eid = cfo.post("/api/finance/money-in/dues", json={
        "member_id": org["student"].id, "amount": 600, "method_id": fin["cash"].id}).json()["id"]
    # another holder (same Lead level as the cfo) without finance.edit
    other = login("mech_lead")
    level = db_session.get(AccessLevel, org["mech_lead"].access_level_id)
    assert "finance.handle_cash" in json.loads(level.privileges)  # Lead level shared with cfo
    assert other.patch(f"/api/finance/entries/dues/{eid}", json={"amount": 1}).status_code == 403
    assert cfo.patch(f"/api/finance/entries/dues/{eid}", json={"amount": 650}).status_code == 200
    assert db_session.get(DuesPayment, eid).amount == 650
    hist = login("admin").get(f"/api/bulk/dues_payments/{eid}/history").json()
    assert {h["action"] for h in hist} >= {"create", "update"}
    assert login("admin").delete(f"/api/finance/entries/dues/{eid}").status_code == 200
    db_session.expire_all()
    assert db_session.get(DuesPayment, eid) is None


def test_deleted_entry_restores_with_its_holder(login, org, fin, db_session):
    cfo = login("cfo")
    eid = cfo.post("/api/finance/money-out", json={
        "item": "Bolts", "amount": 50, "method_id": fin["cash"].id}).json()["id"]
    assert cfo.delete(f"/api/finance/entries/spending/{eid}").status_code == 200
    trash = login("admin").get("/api/bulk/spendings/trash").json()
    r = login("admin").post(f"/api/bulk/spendings/restore/{trash[0]['id']}")
    assert r.status_code == 200 and r.json()["ok"], r.text
    db_session.expire_all()
    assert db_session.get(Spending, eid).holder_id == org["cfo"].id


def test_grid_insert_stamps_the_editor_as_holder(login, org, fin, db_session):
    r = login("admin").post("/api/bulk/dues_payments", json={"rows": [{
        "id": "", "season_id": str(fin["season"].id), "paid_on": "2026-09-10",
        "member_id": str(org["student"].id), "amount": "200", "method_id": str(fin["cash"].id),
    }]}).json()
    assert r["ok"], r
    p = db_session.query(DuesPayment).one()
    assert p.holder_id == org["admin"].id


def test_linking_a_legacy_party_moves_its_money_to_the_account(login, org, fin, db_session):
    osama = FinanceParty(name="Osama")
    db_session.add(osama)
    db_session.flush()
    db_session.add(DuesPayment(season_id=fin["season"].id, member_id=org["student"].id,
                               paid_on=date(2026, 9, 2), amount=700, method_id=fin["cash"].id,
                               received_by_id=osama.id))
    db_session.commit()
    rows = login("admin").get("/api/finance/cash").json()["rows"]
    assert next(r for r in rows if r["party_id"] == osama.id)["name"] == "Osama (legacy)"
    osama.user_id = org["cfo"].id
    db_session.commit()
    rows = login("admin").get("/api/finance/cash").json()["rows"]
    assert not any(r["party_id"] == osama.id for r in rows)
    assert next(r for r in rows if r["user_id"] == org["cfo"].id)["total"] == 700


def test_event_dues_tier_is_set_by_finance_admin(login, org, fin, db_session):
    assert login("cfo").put(f"/api/finance/events/{fin['other'].id}/dues-tier",
                            json={"tier_id": fin["member"].id}).status_code == 403
    assert login("admin").put(f"/api/finance/events/{fin['other'].id}/dues-tier",
                              json={"tier_id": fin["member"].id}).status_code == 200
    rows = {r["member_id"]: r for r in login("admin").get("/api/finance/dues").json()["rows"]}
    assert rows[org["sw_emp"].id]["tier"] == "Member"


def test_form_options(login, org, fin):
    body = login("cfo").get("/api/finance/form-options").json()
    assert body["can_handle_cash"] and not body["can_edit"]
    rov = next(e for e in body["events"] if e["name"] == "ROV27")
    assert [t["name"] for t in rov["teams"]] == ["ROV27 team"]
    assert {o["member_id"] for o in body["owing"]} == {org["student"].id, org["comp_member"].id}
    assert org["cfo"].id in {h["id"] for h in body["holders"]}


def test_finance_tables_are_edited_only_from_finance(login, org, fin):
    admin = login("admin")
    listed = {t["key"] for t in admin.get("/api/bulk/tables").json()}
    assert "spendings" not in listed and "dues_payments" not in listed and "events" in listed
    # but the Finance page's Advanced sheets still read and write them
    assert admin.get("/api/bulk/spendings").status_code == 200
