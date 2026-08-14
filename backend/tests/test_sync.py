"""Live two-way reconcile: the symmetric DB<->Sheets mirror used by the bulk
data editor. A row deleted in the sheet is deleted in the DB; a row created in
the app is never mistaken for a sheet-side deletion; and a validation error in
the sheet leaves the tab untouched rather than pushing broken data over it."""

import pytest

from app.core import gsheets
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
