"""Shared low-level Google Sheets client: credential/auth plumbing used by
both the inventory mirror (app/domains/inventory/sheets.py) and the
structural-data sync/rebuild domain (app/domains/sync)."""

from __future__ import annotations

import re
from pathlib import Path

from app.core.config import settings

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def credentials_available() -> bool:
    """True if the libraries import and a service-account key file is present.
    Enough to read/write any sheet shared with the service account."""
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


def parse_spreadsheet_id(url_or_id: str) -> str:
    """Accept a full Google Sheets URL or a bare spreadsheet id."""
    value = (url_or_id or "").strip()
    match = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", value)
    return match.group(1) if match else value


def open_spreadsheet(spreadsheet_id: str):
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
    is treated as the header row, UNLESS it is the frozen mirror-banner row (a
    single non-empty cell starting with '['), in which case the second row is
    the real header. Raises RuntimeError if credentials are missing."""
    if not credentials_available():
        raise RuntimeError("Google Sheets credentials are not configured")
    spreadsheet = open_spreadsheet(spreadsheet_id)
    ws = spreadsheet.worksheet(worksheet) if worksheet else spreadsheet.sheet1
    values = ws.get_all_values()
    if not values:
        return [], []
    start = 1
    if values[0] and values[0][0].strip().startswith("[") and all(
        not c.strip() for c in values[0][1:]
    ):
        start = 2  # skip the frozen banner row
    headers = [h.strip() for h in values[start - 1]]
    rows = [
        {headers[i]: (cell if i < len(row) else "") for i, cell in enumerate(row[: len(headers)])}
        for row in values[start:]
        if any(c.strip() for c in row)  # skip blank rows
    ]
    return headers, rows


def write_worksheet(
    spreadsheet_id: str,
    worksheet: str,
    header: list[str],
    rows: list[list[str]],
    banner: str | None = None,
) -> None:
    """Overwrite a worksheet wholesale: an optional frozen banner row, then the
    header, then the data. Creates the worksheet if it doesn't exist yet."""
    import gspread

    spreadsheet = open_spreadsheet(spreadsheet_id)
    try:
        ws = spreadsheet.worksheet(worksheet)
    except gspread.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=worksheet, rows=max(100, len(rows) + 2), cols=max(len(header), 1))

    grid = ([[banner] + [""] * (len(header) - 1)] if banner else []) + [header] + rows
    ws.clear()
    ws.update(grid, "A1")
    if banner:
        try:
            ws.freeze(rows=1)
        except Exception:  # noqa: BLE001 — freezing is cosmetic, never fatal
            pass
