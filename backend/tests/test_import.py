"""Google Sheet import — the sheet read is mocked so no network/creds needed."""

import pytest

from app.domains.inventory import sheets

SHEET = [
    ["Name", "Qty", "Category", "Asset", "Where"],
    ["Arduino Uno", "100", "Microcontrollers", "ARD-1", "Lab A"],
    ["Raspberry Pi", "15", "SBC", "RPI-1", "Cabinet"],
    ["", "5", "junk", "", ""],  # blank name → skipped
]


@pytest.fixture()
def fake_sheet(monkeypatch):
    headers = [h.strip() for h in SHEET[0]]
    rows = [
        {headers[i]: c for i, c in enumerate(r)}
        for r in SHEET[1:]
        if any(c.strip() for c in r)
    ]
    monkeypatch.setattr(sheets, "credentials_available", lambda: True)
    monkeypatch.setattr(sheets, "read_worksheet", lambda sid, ws=None: (headers, rows))
    return headers, rows


MAPPING = {
    "name": "Name",
    "quantity": "Qty",
    "category": "Category",
    "asset_tag": "Asset",
    "location": "Where",
}


def test_preview_returns_headers_and_rows(login, org, fake_sheet):
    r = login("cto").post(
        "/api/inventory/import/preview",
        json={"source": "https://docs.google.com/spreadsheets/d/ABC123/edit#gid=0"},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["spreadsheet_id"] == "ABC123"  # parsed from the URL
    assert data["headers"] == ["Name", "Qty", "Category", "Asset", "Where"]
    assert data["total"] == 3  # 3 non-blank rows (the blank-name one is skipped at import)


def test_import_creates_items(login, org, fake_sheet):
    r = login("cto").post(
        "/api/inventory/import",
        json={"spreadsheet_id": "ABC123", "mapping": MAPPING, "team_lead_id": org["team_lead"].id},
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"created": 2, "updated": 0, "skipped": 1, "errors": []}  # blank-name row skipped

    items = {i["name"]: i for i in login("cto").get("/api/inventory").json()}
    assert items["Arduino Uno"]["quantity"] == 100
    assert items["Arduino Uno"]["asset_tag"] == "ARD-1"
    assert items["Arduino Uno"]["team_lead"]["id"] == org["team_lead"].id


def test_import_upserts_by_asset_tag(login, org, fake_sheet):
    login("cto").post("/api/inventory/import", json={"spreadsheet_id": "ABC", "mapping": MAPPING})
    # second run updates rather than duplicating (blank-name row still skipped)
    r = login("cto").post("/api/inventory/import", json={"spreadsheet_id": "ABC", "mapping": MAPPING})
    assert r.json() == {"created": 0, "updated": 2, "skipped": 1, "errors": []}
    assert len(login("cto").get("/api/inventory").json()) == 2

    # with upsert disabled the existing rows are skipped (2 existing + 1 blank name)
    r = login("cto").post(
        "/api/inventory/import",
        json={"spreadsheet_id": "ABC", "mapping": MAPPING, "upsert": False},
    )
    assert r.json()["created"] == 0 and r.json()["skipped"] == 3


def test_import_requires_name_mapping(login, org, fake_sheet):
    r = login("cto").post("/api/inventory/import", json={"spreadsheet_id": "ABC", "mapping": {"quantity": "Qty"}})
    assert r.status_code == 400


def test_import_is_staff_only_and_needs_credentials(login, org, monkeypatch):
    # non-staff blocked before anything else
    assert login("student").post(
        "/api/inventory/import", json={"spreadsheet_id": "X", "mapping": {"name": "Name"}}
    ).status_code == 403
    # staff but no credentials → 503
    monkeypatch.setattr(sheets, "credentials_available", lambda: False)
    assert login("cto").post(
        "/api/inventory/import", json={"spreadsheet_id": "X", "mapping": {"name": "Name"}}
    ).status_code == 503
