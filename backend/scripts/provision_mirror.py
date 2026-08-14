"""Provision a dedicated Google Sheets mirror spreadsheet for one environment.

The live two-way mirror needs a *durable, per-environment* spreadsheet — one for
dev, a separate one for prod — not a single throwaway "test" sheet shared by
everything (editing the dev sheet must never touch prod data). This script
creates that spreadsheet with the service account, shares it with the people who
should edit it, writes every portal tab into it, and seeds the sync snapshot so
the first reconcile is a clean no-op.

It prints the new spreadsheet id + URL at the end. Put that id in the
environment's config as GOOGLE_SHEETS_SPREADSHEET_ID (dev .env / prod secret),
then paste scripts/sheets_live_sync.gs into that sheet's Apps Script and run
`setup` once.

Usage (from backend/, with the venv):
    DATABASE_URL=sqlite:///./portal_dev.db \\
        GOOGLE_SHEETS_CREDENTIALS_FILE=/path/to/sa.json \\
        .venv/bin/python -m scripts.provision_mirror \\
            --title "MTR Portal Mirror (dev)" --share you@example.com

Creating a spreadsheet needs Drive access, so this script authorizes with the
Drive scope in addition to Sheets (the running server only ever needs Sheets).
The service account owns the new file; --share grants each listed email edit
access so a human can open it.
"""

import argparse
import sys

from app.core import gsheets
from app.core.database import SessionLocal
from app.domains.sync import service as sync

# The service account owns files it creates; humans need explicit sharing.
CREATE_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def _client():
    """gspread client authorized with Sheets + Drive (Drive is needed to create
    and share a spreadsheet, which the server-side client never does)."""
    import gspread
    from google.oauth2.service_account import Credentials

    if not gsheets.credentials_available():
        sys.exit(
            "No Google service-account key found. Set GOOGLE_SHEETS_CREDENTIALS_FILE "
            "or GOOGLE_SHEETS_CREDENTIALS_B64."
        )
    # Reuse the same key-loading as the app, but widen the scopes for creation.
    from app.core.config import settings

    if settings.google_sheets_credentials_b64:
        import base64
        import json

        info = json.loads(base64.b64decode(settings.google_sheets_credentials_b64))
        creds = Credentials.from_service_account_info(info, scopes=CREATE_SCOPES)
    else:
        creds = Credentials.from_service_account_file(
            settings.google_sheets_credentials_file, scopes=CREATE_SCOPES
        )
    return gspread.authorize(creds)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--title", required=True, help='Spreadsheet name, e.g. "MTR Portal Mirror (dev)"')
    ap.add_argument(
        "--share",
        action="append",
        default=[],
        metavar="EMAIL",
        help="Email to grant edit access (repeatable). Without any, only the service account can open it.",
    )
    args = ap.parse_args()

    client = _client()
    print(f"Creating spreadsheet {args.title!r} …")
    ss = client.create(args.title)
    for email in args.share:
        ss.share(email, perm_type="user", role="writer", notify=False)
        print(f"  shared with {email}")

    # gspread creates a default 'Sheet1'; the tab writes below add the real tabs,
    # and we drop the placeholder at the end.
    print("Writing tabs from the database …")
    db = SessionLocal()
    try:
        counts = sync.export_all(db, ss.id)
        for tab in sync.TAB_ORDER:
            sync._snapshot(db, tab)  # seed synced_ids so the first reconcile is clean
    finally:
        db.close()

    try:
        ss.del_worksheet(ss.worksheet("Sheet1"))
    except Exception:  # noqa: BLE001 — placeholder may already be gone
        pass

    print("\nDone. Tab row counts:")
    for tab, n in counts.items():
        print(f"  {tab:24} {n}")
    print(f"\nSpreadsheet id:  {ss.id}")
    print(f"URL:             https://docs.google.com/spreadsheets/d/{ss.id}/edit")
    print("\nNext:")
    print("  1. Set GOOGLE_SHEETS_SPREADSHEET_ID to the id above for THIS environment.")
    print("  2. Open the sheet -> Extensions -> Apps Script, paste scripts/sheets_live_sync.gs,")
    print("     set TOKEN to your SHEETS_SYNC_TOKEN, and run setup() once.")


if __name__ == "__main__":
    main()
