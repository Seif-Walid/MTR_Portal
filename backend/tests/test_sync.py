"""Sheets sync + Rebuild-from-Sheets: outbound export tracking, and the
destructive inbound path (dry-run validation, the confirm-phrase gate,
snapshot-before-truncate, and that dependent operational data — tasks,
sessions, notifications — is cleared rather than left dangling)."""

import json

import pytest
from sqlalchemy import func, select

from app.core import gsheets
from app.domains.auth.models import AuthSession
from app.domains.tasks.models import Task
from app.domains.users.models import User

SPREADSHEET = "TESTSHEET"


@pytest.fixture()
def fake_sheets(monkeypatch):
    """In-memory stand-in for Sheets: read_worksheet serves from `data`,
    write_worksheet records into `written`."""
    data: dict[str, list[dict[str, str]]] = {}
    written: dict[str, list[list[str]]] = {}

    monkeypatch.setattr(gsheets, "credentials_available", lambda: True)

    def fake_read(spreadsheet_id, worksheet=None):
        rows = data.get(worksheet, [])
        headers = list(rows[0].keys()) if rows else []
        return headers, rows

    def fake_write(spreadsheet_id, worksheet, header, rows, banner=None):
        written[worksheet] = rows

    monkeypatch.setattr(gsheets, "read_worksheet", fake_read)
    monkeypatch.setattr(gsheets, "write_worksheet", fake_write)
    return data, written


def _row(**kw) -> dict[str, str]:
    return {k: str(v) if v is not None else "" for k, v in kw.items()}


# --- status --------------------------------------------------------------
def test_status_exposes_org_name_to_any_user(login, org):
    """The frontend's rebuild confirm-phrase must come from here, not a
    hardcoded literal, or it silently breaks the moment ORG_NAME changes."""
    r = login("student").get("/api/sync/status")
    assert r.status_code == 200
    body = r.json()
    assert "org_name" in body
    assert body["org_name"] == "Mind-Tech Robotics"  # settings default in tests


# --- permissions -------------------------------------------------------
def test_only_org_manager_can_export_or_dry_run(login, org, fake_sheets):
    assert login("cto").post("/api/sync/export", json={"spreadsheet_id": SPREADSHEET}).status_code == 403
    assert login("ceo").post("/api/sync/export", json={"spreadsheet_id": SPREADSHEET}).status_code == 200
    assert login("cto").post("/api/sync/rebuild/dry-run", json={"spreadsheet_id": SPREADSHEET}).status_code == 403
    assert login("admin").post("/api/sync/rebuild/dry-run", json={"spreadsheet_id": SPREADSHEET}).status_code == 200


def test_commit_requires_admin_or_ceo_specifically(login, org, fake_sheets):
    # CTO is high-staff but neither admin nor CEO — spec says Admin/CEO only for the destructive path
    r = login("cto").post(
        "/api/sync/rebuild/commit",
        json={"spreadsheet_id": SPREADSHEET, "confirm_phrase": "Mind-Tech Robotics"},
    )
    assert r.status_code == 403


def test_commit_requires_exact_confirm_phrase(login, org, fake_sheets):
    r = login("admin").post(
        "/api/sync/rebuild/commit",
        json={"spreadsheet_id": SPREADSHEET, "confirm_phrase": "nope"},
    )
    assert r.status_code == 400
    assert "type" in r.json()["detail"].lower()


# --- export --------------------------------------------------------------
def test_export_writes_every_tab_and_updates_tracking(login, org, fake_sheets):
    data, written = fake_sheets
    r = login("admin").post("/api/sync/export", json={"spreadsheet_id": SPREADSHEET})
    assert r.status_code == 200
    counts = r.json()
    assert counts["people"] == len(org)  # every seeded fixture user
    assert set(written.keys()) == set(counts.keys())

    statuses = login("admin").get("/api/sync/exports").json()
    people_status = next(s for s in statuses if s["tab"] == "people")
    assert people_status["is_dirty"] is False
    assert people_status["row_count"] == len(org)
    assert people_status["last_synced_at"] is not None


# --- dry run ---------------------------------------------------------------
def test_dry_run_never_touches_db(login, org, fake_sheets, db_session):
    data, _ = fake_sheets
    data["people"] = [_row(id=999, email="new@t.local", full_name="New Person", access_level="", is_active="true")]
    before = db_session.scalar(select(func.count()).select_from(User))

    r = login("admin").post("/api/sync/rebuild/dry-run", json={"spreadsheet_id": SPREADSHEET})
    assert r.status_code == 200
    report = r.json()
    assert report["ok"] is True
    assert report["tab_counts"]["people"] == 1

    db_session.expire_all()
    after = db_session.scalar(select(func.count()).select_from(User))
    assert before == after  # nothing written


def test_dry_run_flags_unresolved_reference(login, org, fake_sheets):
    data, _ = fake_sheets
    data["people"] = [_row(id=1, email="a@t.local", full_name="A", access_level="", is_active="true")]
    data["positions"] = [_row(id=1, title="CEO", parent_id="", occupant_ids="999", is_technical="false")]

    r = login("admin").post("/api/sync/rebuild/dry-run", json={"spreadsheet_id": SPREADSHEET})
    report = r.json()
    assert report["ok"] is False
    assert any("occupant_ids" in e and "999" in e for e in report["errors"])


def test_dry_run_flags_unknown_access_level(login, org, fake_sheets):
    data, _ = fake_sheets
    data["people"] = [_row(id=1, email="a@t.local", full_name="A", access_level="Wizard", is_active="true")]
    r = login("admin").post("/api/sync/rebuild/dry-run", json={"spreadsheet_id": SPREADSHEET})
    report = r.json()
    assert report["ok"] is False
    assert any("unknown access level" in e.lower() for e in report["errors"])


# --- commit (the destructive path) -----------------------------------------
def _minimal_valid_sheet(data: dict) -> None:
    """A small, internally-consistent dataset: one person, one position (that
    person as CEO), one event with a category/team/member, one location
    + item + movement. Ids are deliberately disjoint from the org fixture's
    ids to prove the old data was actually replaced."""
    data["people"] = [_row(id=501, email="rebuilt@t.local", full_name="Rebuilt Person",
                           department="", access_level="Exec", manager_id="", is_active="true")]
    data["positions"] = [_row(id=601, title="CEO", parent_id="", occupant_ids="501", is_technical="false")]
    data["events"] = [_row(id=701, name="Rebuilt Cup", description="", start_date="", end_date="", status="active")]
    data["event_categories"] = [_row(id=801, event_id="701", name="Senior")]
    data["event_teams"] = [_row(id=901, category_id="801", name="Team A")]
    data["event_team_members"] = [_row(id=1101, team_id="901", user_id="501")]
    data["inventory_locations"] = [_row(id=1201, name="Shelf A", kind="shelf", notes="")]
    data["inventory_items"] = [_row(id=1301, name="Widget", category="", asset_tag="", sku="",
                                    quantity=10, low_stock_threshold=0, unit="unit", location="",
                                    condition="good", notes="", team_lead_id="501")]
    data["inventory_movements"] = [_row(id=1401, item_id="1301", quantity=10, from_location_id="",
                                        from_holder_id="", to_location_id="1201", to_holder_id="",
                                        actor_id="501", reason="stock-in", created_at="")]


def test_commit_replaces_the_database_and_snapshots_first(login, org, fake_sheets, db_session):
    data, written = fake_sheets
    _minimal_valid_sheet(data)

    # something pre-existing that must be cleared as a dependent of the old people
    old_cto_id = org["cto"].id
    task = Task(title="pre-existing", assigner_id=org["ceo"].id, assignee_id=old_cto_id)
    db_session.add(task)
    db_session.commit()

    admin_client = login("admin")
    login("cto")  # a second session, also expected to be cleared by the rebuild
    sessions_before = db_session.scalar(select(func.count()).select_from(AuthSession))
    assert sessions_before >= 2

    r = admin_client.post(
        "/api/sync/rebuild/commit",
        json={"spreadsheet_id": SPREADSHEET, "confirm_phrase": "Mind-Tech Robotics"},
    )
    assert r.status_code == 200, r.text
    report = r.json()
    assert report["ok"] is True and report["committed"] is True
    assert report["tab_counts"]["people"] == 1
    assert report["snapshot_path"]

    import os
    assert os.path.isfile(report["snapshot_path"])
    snapshot = json.loads(open(report["snapshot_path"]).read())
    assert len(snapshot["people"]) == len(org)  # snapshot taken BEFORE truncation

    db_session.expire_all()
    # old people are gone
    assert db_session.get(User, old_cto_id) is None
    # the new, rebuilt person exists with the id from the sheet
    rebuilt = db_session.get(User, 501)
    assert rebuilt is not None and rebuilt.email == "rebuilt@t.local"
    # every pre-rebuild session, including the admin's own, was cleared —
    # everyone must sign in again after a rebuild
    assert db_session.get(AuthSession, admin_client.cookies["portal_session"]) is None
    assert db_session.scalar(select(func.count()).select_from(AuthSession)) == 0
    # dependent data referencing the old world is gone, not dangling
    assert db_session.get(Task, task.id) is None

    # the auto re-export after a successful rebuild wrote every tab
    assert written.get("people") and written["people"][0][1] == "rebuilt@t.local"


# --- live two-way reconcile ------------------------------------------------
def test_reconcile_two_way_delete_and_app_row_survival(org, fake_sheets, db_session):
    """The mirror is symmetric: a row deleted in the sheet is deleted in the DB,
    but a row created in the app (absent from the sheet, absent from the prior
    snapshot) is never mistaken for a sheet-side deletion."""
    from app.domains.sync import service as sync

    data, _ = fake_sheets

    # an isolated person nobody references, so deleting it can't break a FK
    temp = User(email="temp@t.local", full_name="Temp", hashed_password="x", is_active=True)
    db_session.add(temp)
    db_session.commit()
    temp_id = temp.id

    def mirror_people() -> None:
        header, rows = sync._export_people(db_session)
        data["people"] = [dict(zip(header, r)) for r in rows]

    # establish the baseline snapshot with the sheet mirroring the DB
    mirror_people()
    sync.reconcile_tab(db_session, SPREADSHEET, "people")

    # 1) delete temp's row in the sheet -> reconcile deactivates it (People's
    #    soft-delete) so it leaves both the DB mirror and the grid.
    data["people"] = [r for r in data["people"] if r["id"] != str(temp_id)]
    res = sync.reconcile_tab(db_session, SPREADSHEET, "people")
    assert res["ok"], res
    db_session.expire_all()
    assert db_session.get(User, temp_id).is_active is False

    # 2) a person created in the app but not yet in the sheet must survive a
    #    reconcile (it isn't in the previous snapshot -> not a sheet deletion).
    fresh = User(email="fresh@t.local", full_name="Fresh", hashed_password="x", is_active=True)
    db_session.add(fresh)
    db_session.commit()
    fresh_id = fresh.id
    res2 = sync.reconcile_tab(db_session, SPREADSHEET, "people")
    assert res2["ok"], res2
    db_session.expire_all()
    assert db_session.get(User, fresh_id).is_active is True


def test_reconcile_bad_sheet_data_does_not_push_over_it(org, fake_sheets, db_session):
    """A validation error in the sheet must leave the tab untouched (so the user
    can fix it) — reconcile records the error and refuses to push."""
    from app.domains.sync import service as sync

    data, written = fake_sheets
    data["people"] = [_row(id=1, email="a@t.local", full_name="A", department="",
                           access_level="Wizard", manager_id="", is_active="true")]
    res = sync.reconcile_tab(db_session, SPREADSHEET, "people")
    assert res["ok"] is False
    assert "people" not in written  # never pushed over the broken sheet


def test_failed_dry_run_blocks_commit(login, org, fake_sheets, db_session):
    data, written = fake_sheets
    data["people"] = [_row(id=1, email="a@t.local", full_name="A", access_level="not_a_level", is_active="true")]

    before = db_session.scalar(select(func.count()).select_from(User))
    r = login("admin").post(
        "/api/sync/rebuild/commit",
        json={"spreadsheet_id": SPREADSHEET, "confirm_phrase": "Mind-Tech Robotics"},
    )
    assert r.status_code == 200
    report = r.json()
    assert report["ok"] is False and report["committed"] is False
    assert not written  # never got to the write-back step

    db_session.expire_all()
    after = db_session.scalar(select(func.count()).select_from(User))
    assert before == after  # nothing destroyed

    history = login("admin").get("/api/sync/rebuild/history").json()
    assert history[0]["status"] == "failed"
