"""Inventory import from an uploaded .csv — column mapping, upsert, gating."""

import json

SHEET = [
    ["Name", "Qty", "Category", "Asset", "Where"],
    ["Arduino Uno", "100", "Microcontrollers", "ARD-1", "Lab A"],
    ["Raspberry Pi", "15", "SBC", "RPI-1", "Cabinet"],
    ["", "5", "junk", "", ""],  # blank name → skipped
]
CSV = "\n".join(",".join(r) for r in SHEET).encode()

MAPPING = {
    "name": "Name",
    "quantity": "Qty",
    "category": "Category",
    "asset_tag": "Asset",
    "location": "Where",
}


def _import(client, mapping=MAPPING, **form):
    data = {"mapping": json.dumps(mapping), **{k: str(v) for k, v in form.items()}}
    return client.post(
        "/api/inventory/import/file",
        data=data,
        files={"file": ("items.csv", CSV, "text/csv")},
    )


def test_preview_returns_headers_and_rows(login, org):
    r = login("cto").post(
        "/api/inventory/import/file/preview",
        files={"file": ("items.csv", CSV, "text/csv")},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["sheets"] is None  # CSV has no tabs
    assert data["headers"] == ["Name", "Qty", "Category", "Asset", "Where"]
    assert data["total"] == 3  # 3 non-blank rows (the blank-name one is skipped at import)


def test_import_creates_items(login, org):
    r = _import(login("cto"), team_lead_id=org["team_lead"].id)
    assert r.status_code == 200, r.text
    assert r.json() == {"created": 2, "updated": 0, "skipped": 1, "errors": []}  # blank-name row skipped

    items = {i["name"]: i for i in login("cto").get("/api/inventory").json()}
    assert items["Arduino Uno"]["quantity"] == 100
    assert items["Arduino Uno"]["asset_tag"] == "ARD-1"
    assert items["Arduino Uno"]["team_lead"]["id"] == org["team_lead"].id


def test_import_upserts_by_asset_tag(login, org):
    _import(login("cto"))
    # second run updates rather than duplicating (blank-name row still skipped)
    r = _import(login("cto"))
    assert r.json() == {"created": 0, "updated": 2, "skipped": 1, "errors": []}
    assert len(login("cto").get("/api/inventory").json()) == 2

    # with upsert disabled the existing rows are skipped (2 existing + 1 blank name)
    r = _import(login("cto"), upsert="false")
    assert r.json()["created"] == 0 and r.json()["skipped"] == 3


def test_import_requires_name_mapping(login, org):
    assert _import(login("cto"), mapping={"quantity": "Qty"}).status_code == 400


def test_import_is_staff_only(login, org):
    assert _import(login("student")).status_code == 403
