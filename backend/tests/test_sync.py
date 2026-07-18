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
    data["people"] = [_row(id=999, email="new@t.local", full_name="New Person", roles="", is_active="true")]
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
    data["people"] = [_row(id=1, email="a@t.local", full_name="A", roles="", is_active="true")]
    data["positions"] = [_row(id=1, title="CEO", parent_id="", occupant_ids="999", is_technical="false")]

    r = login("admin").post("/api/sync/rebuild/dry-run", json={"spreadsheet_id": SPREADSHEET})
    report = r.json()
    assert report["ok"] is False
    assert any("occupant_ids" in e and "999" in e for e in report["errors"])


def test_dry_run_flags_unknown_role(login, org, fake_sheets):
    data, _ = fake_sheets
    data["people"] = [_row(id=1, email="a@t.local", full_name="A", roles="wizard", is_active="true")]
    r = login("admin").post("/api/sync/rebuild/dry-run", json={"spreadsheet_id": SPREADSHEET})
    report = r.json()
    assert report["ok"] is False
    assert any("unknown role" in e.lower() for e in report["errors"])


# --- commit (the destructive path) -----------------------------------------
def _minimal_valid_sheet(data: dict) -> None:
    """A small, internally-consistent dataset: one person, one position (that
    person as CEO), one competition with a category/team/member, one location
    + item + movement. Ids are deliberately disjoint from the org fixture's
    ids to prove the old data was actually replaced."""
    data["people"] = [_row(id=501, email="rebuilt@t.local", full_name="Rebuilt Person",
                           department="", roles="ceo", manager_id="", is_active="true")]
    data["positions"] = [_row(id=601, title="CEO", parent_id="", occupant_ids="501", is_technical="false")]
    data["competitions"] = [_row(id=701, name="Rebuilt Cup", description="", start_date="", end_date="", status="active")]
    data["competition_categories"] = [_row(id=801, competition_id="701", name="Senior")]
    data["competition_teams"] = [_row(id=901, category_id="801", name="Team A")]
    data["competition_team_members"] = [_row(id=1101, team_id="901", user_id="501")]
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


def test_failed_dry_run_blocks_commit(login, org, fake_sheets, db_session):
    data, written = fake_sheets
    data["people"] = [_row(id=1, email="a@t.local", full_name="A", roles="not_a_role", is_active="true")]

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
