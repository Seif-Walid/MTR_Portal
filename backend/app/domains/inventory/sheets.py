"""Google Sheets mirror — the app is king.

The portal database is the single source of truth. "Sync to Sheets" pushes a
read-only snapshot of the whole inventory into a spreadsheet so people who
prefer a spreadsheet can still read it; real edits always happen in the portal
and the next sync overwrites the sheet.

Everything degrades gracefully: if the gspread/google-auth libraries or the
service-account credentials aren't configured, is_configured() is False and the
UI disables the Sync button instead of erroring.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.core.config import settings
from app.domains.inventory.models import AllocationPurpose, InventoryItem

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

PURPOSE_LABELS = {
    AllocationPurpose.TRAINING: "Training",
    AllocationPurpose.COMPETITION: "Competition",
    AllocationPurpose.RESEARCH: "R&D",
    AllocationPurpose.BORROWED: "Borrowed",
    AllocationPurpose.OTHER: "Other",
}

HEADER = [
    "Name",
    "Category",
    "Asset tag",
    "Total",
    "Unit",
    "In use",
    "Free",
    "Usage breakdown",
    "Holders",
    "Location",
    "Condition",
    "Team",
    "Notes",
]


def credentials_available() -> bool:
    """True if the libraries import and a service-account key file is present.
    Enough to read/import from any sheet shared with the service account."""
    if not settings.google_sheets_credentials_file:
        return False
    if not Path(settings.google_sheets_credentials_file).is_file():
        return False
    try:
        import gspread  # noqa: F401
        import google.auth  # noqa: F401
    except ImportError:
        return False
    return True


def is_configured() -> bool:
    """True when both credentials AND a default push-target spreadsheet are set
    (drives the 'Sync to Sheets' button)."""
    return credentials_available() and bool(settings.google_sheets_spreadsheet_id)


def parse_spreadsheet_id(url_or_id: str) -> str:
    """Accept a full Google Sheets URL or a bare spreadsheet id."""
    value = (url_or_id or "").strip()
    match = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", value)
    return match.group(1) if match else value


def _open(spreadsheet_id: str):
    """Authorize with the service account and open a spreadsheet by id."""
    import gspread
    from google.oauth2.service_account import Credentials

    creds = Credentials.from_service_account_file(
        settings.google_sheets_credentials_file, scopes=SCOPES
    )
    return gspread.authorize(creds).open_by_key(spreadsheet_id)


def read_worksheet(
    spreadsheet_id: str, worksheet: str | None = None
) -> tuple[list[str], list[dict[str, str]]]:
    """Return (headers, rows) from a sheet, rows keyed by header. The first row
    is treated as the header row. Raises RuntimeError if credentials are missing."""
    if not credentials_available():
        raise RuntimeError("Google Sheets credentials are not configured")
    spreadsheet = _open(spreadsheet_id)
    ws = spreadsheet.worksheet(worksheet) if worksheet else spreadsheet.sheet1
    values = ws.get_all_values()
    if not values:
        return [], []
    headers = [h.strip() for h in values[0]]
    rows = [
        {headers[i]: (cell if i < len(row) else "") for i, cell in enumerate(row[: len(headers)])}
        for row in values[1:]
        if any(c.strip() for c in row)  # skip blank rows
    ]
    return headers, rows


def _usage_breakdown(item: InventoryItem) -> str:
    parts = [
        f"{PURPOSE_LABELS.get(purpose, purpose)}: {qty}"
        for purpose, qty in sorted(item.by_purpose.items())
    ]
    return ", ".join(parts)


def _holders(item: InventoryItem) -> str:
    """e.g. 'Seif — 2 R&D; Seif — 1 Competition (RoboCup)'."""
    lines = []
    for a in item.allocations:
        if a.holder is None:
            continue
        label = PURPOSE_LABELS.get(a.purpose, a.purpose)
        if a.display_label:
            label = f"{label} ({a.display_label})"
        lines.append(f"{a.holder.full_name} — {a.quantity} {label}")
    return "; ".join(lines)


def _row(item: InventoryItem) -> list[str]:
    return [
        item.name,
        item.category or "",
        item.asset_tag or "",
        str(item.quantity),
        item.unit,
        str(item.in_use),
        str(item.free),
        _usage_breakdown(item),
        _holders(item),
        item.location or "",
        item.condition,
        item.team_lead.full_name if item.team_lead else "General storage",
        item.notes,
    ]


def push_inventory(items: list[InventoryItem]) -> dict[str, object]:
    """Overwrite the target worksheet with the current inventory snapshot.
    Raises RuntimeError if Sheets isn't configured (callers gate on
    is_configured() first)."""
    if not is_configured():
        raise RuntimeError("Google Sheets sync is not configured")

    import gspread

    spreadsheet = _open(settings.google_sheets_spreadsheet_id)

    try:
        worksheet = spreadsheet.worksheet(settings.google_sheets_worksheet)
    except gspread.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(
            title=settings.google_sheets_worksheet, rows=100, cols=len(HEADER)
        )

    rows = [HEADER] + [_row(i) for i in items]
    worksheet.clear()
    worksheet.update(rows, "A1")

    return {"synced": len(items), "worksheet": settings.google_sheets_worksheet}
