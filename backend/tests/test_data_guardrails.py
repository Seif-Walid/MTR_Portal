"""Data-entry guardrails on the bulk grid: per-row audit history, the recycle
bin, retired rows staying out of reach, edit conflicts, validation metadata,
column visibility, the guided importer and the season lock."""

from datetime import date

import pytest

from app.domains.finance.models import FinanceOption, FinanceParty, FinanceSeason, Spending


@pytest.fixture()
def season(db_session):
    s = FinanceSeason(name="S5", status="active", start_date=date(2026, 9, 1), usd_rate=50)
    db_session.add(s)
    db_session.flush()
    cash = FinanceOption(list_key="payment_method", value="Cash", sort_order=0)
    db_session.add(cash)
    db_session.add(FinanceParty(name="Osama"))
    db_session.commit()
    return s


def _add_spending(admin, season_id, item="Motor", count="2", unit_cost="100"):
    res = admin.post("/api/bulk/spendings", json={
        "rows": [{"id": "", "season_id": str(season_id), "item": item, "count": count, "unit_cost": unit_cost}],
        "partial": True,
    }).json()
    assert res["ok"], res
    return res["ids"]["0"]


# --- phase 1: audit history + recycle bin --------------------------------------
def test_update_writes_field_level_history(login, org, season):
    admin = login("admin")
    sid = _add_spending(admin, season.id)
    admin.post("/api/bulk/spendings", json={"rows": [{"id": str(sid), "count": "3"}], "partial": True})
    hist = admin.get(f"/api/bulk/spendings/{sid}/history").json()
    assert [h["action"] for h in hist] == ["update", "create"]
    assert hist[0]["detail"]["changes"] == {"count": ["2", "3"]}
    assert hist[0]["actor"]
    assert hist[1]["detail"]["row"]["item"] == "Motor"


def test_hard_delete_goes_to_recycle_bin_and_restores(login, org, season, db_session):
    admin = login("admin")
    sid = _add_spending(admin, season.id, item="Wheel")
    assert admin.post("/api/bulk/spendings", json={"deletes": [sid]}).json()["ok"]
    assert db_session.get(Spending, sid) is None

    bin_ = admin.get("/api/bulk/spendings/trash").json()
    assert len(bin_) == 1 and bin_[0]["detail"]["row"]["item"] == "Wheel"
    res = admin.post(f"/api/bulk/spendings/restore/{bin_[0]['id']}")
    assert res.status_code == 200, res.text
    db_session.expire_all()
    restored = db_session.get(Spending, sid)
    assert restored is not None and restored.item == "Wheel" and restored.count == 2
    assert admin.get("/api/bulk/spendings/trash").json() == []
    # a second restore of the same entry is refused
    assert admin.post(f"/api/bulk/spendings/restore/{bin_[0]['id']}").status_code == 409


def test_restore_refused_when_reference_is_gone(login, org, season, db_session):
    admin = login("admin")
    s2 = FinanceSeason(name="Tmp", status="planning")
    db_session.add(s2)
    db_session.commit()
    sid = _add_spending(admin, s2.id, item="Gone")
    admin.post("/api/bulk/spendings", json={"deletes": [sid]})
    admin.post("/api/bulk/finance_seasons", json={"deletes": [s2.id]})
    entry = next(t for t in admin.get("/api/bulk/spendings/trash").json() if t["entity_id"] == sid)
    res = admin.post(f"/api/bulk/spendings/restore/{entry['id']}")
    assert res.status_code == 409 and "restore" in res.json()["detail"].lower()


def test_soft_deleted_rows_are_out_of_reach_and_restorable(login, org, db_session):
    from app.domains.inventory.models import InventoryItem

    admin = login("admin")
    iid = admin.post("/api/bulk/inventory_items", json={
        "rows": [{"id": "", "name": "Servo", "quantity": "4"}], "partial": True}).json()["ids"]["0"]
    admin.post("/api/bulk/inventory_items", json={"deletes": [iid]})
    # a retired row can't be edited and isn't counted
    res = admin.post("/api/bulk/inventory_items", json={"rows": [{"id": str(iid), "quantity": "9"}], "partial": True}).json()
    assert not res["ok"]
    counts = {t["key"]: t["row_count"] for t in admin.get("/api/bulk/tables").json()}
    assert counts["inventory_items"] == 0
    entry = admin.get("/api/bulk/inventory_items/trash").json()[0]
    assert admin.post(f"/api/bulk/inventory_items/restore/{entry['id']}").status_code == 200
    db_session.expire_all()
    assert db_session.get(InventoryItem, iid).deleted_at is None


def test_history_and_trash_need_table_privilege(login, org, season):
    sid = _add_spending(login("admin"), season.id)
    assert login("ceo").get(f"/api/bulk/spendings/{sid}/history").status_code == 403
    assert login("ceo").get("/api/bulk/spendings/trash").status_code == 403


# --- phase 2: per-cell conflicts ------------------------------------------------
def test_stale_cell_is_a_conflict_but_other_cells_save(login, org, season, db_session):
    admin = login("admin")
    sid = _add_spending(admin, season.id, item="Bolt", count="2")
    # someone else changes count 2 -> 5
    admin.post("/api/bulk/spendings", json={"rows": [{"id": str(sid), "count": "5"}], "partial": True})
    # our editor still thinks count is 2, and also edits the note
    res = admin.post("/api/bulk/spendings", json={"rows": [{
        "id": str(sid), "count": "7", "note": "checked", "_base": {"count": "2", "note": ""},
    }], "partial": True}).json()
    conflict = next(e for e in res["errors"] if e["column"] == "count")
    assert conflict["code"] == "conflict" and conflict["current"] == "5" and conflict["by"]
    db_session.expire_all()
    row = db_session.get(Spending, sid)
    assert row.count == 5 and row.note == "checked"


def test_matching_base_or_same_value_is_not_a_conflict(login, org, season):
    admin = login("admin")
    sid = _add_spending(admin, season.id, count="2")
    ok = admin.post("/api/bulk/spendings", json={"rows": [{"id": str(sid), "count": "3", "_base": {"count": "2"}}],
                                                  "partial": True}).json()
    assert ok["ok"], ok
    # stale base, but the cell already holds what we're writing
    same = admin.post("/api/bulk/spendings", json={"rows": [{"id": str(sid), "count": "3", "_base": {"count": "2"}}],
                                                    "partial": True}).json()
    assert same["ok"], same


# --- phase 3: input rules ---------------------------------------------------------
def test_input_rules_are_enforced_and_described(login, org, season, db_session):
    from app.domains.users.models import MemberProfile

    admin = login("admin")
    cols = {c["name"]: c for c in admin.get("/api/bulk/member_profiles").json()["columns"]}
    assert cols["mtr_id"]["pattern"] and cols["mtr_id"]["pattern_hint"]
    res = admin.post("/api/bulk/spendings", json={"rows": [
        {"id": "", "season_id": str(season.id), "item": "X", "count": "-1"}], "partial": True}).json()
    assert res["errors"][0]["column"] == "count" and "at least 0" in res["errors"][0]["message"]
    res = admin.post("/api/bulk/member_profiles", json={"rows": [
        {"id": "", "full_name": "A", "mtr_id": "123"}], "partial": True}).json()
    assert res["errors"][0]["column"] == "mtr_id"
    # a legacy value that breaks a rule can be sent back unchanged
    m = MemberProfile(full_name="Legacy", phone="phone?")
    db_session.add(m)
    db_session.commit()
    ok = admin.post("/api/bulk/member_profiles", json={"rows": [
        {"id": str(m.id), "phone": "phone?", "university": "AUC"}], "partial": True}).json()
    assert ok["ok"], ok
