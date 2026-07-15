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

from app.core import gsheets
from app.core.config import settings
from app.core.gsheets import credentials_available, parse_spreadsheet_id, read_worksheet
from app.domains.inventory.models import AllocationPurpose, InventoryItem

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

__all__ = ["credentials_available", "parse_spreadsheet_id", "read_worksheet", "is_configured", "push_inventory"]


def is_configured() -> bool:
    """True when both credentials AND a default push-target spreadsheet are set
    (drives the 'Sync to Sheets' button)."""
    return credentials_available() and bool(settings.google_sheets_spreadsheet_id)


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

    gsheets.write_worksheet(
        settings.google_sheets_spreadsheet_id,
        settings.google_sheets_worksheet,
        HEADER,
        [_row(i) for i in items],
    )
    return {"synced": len(items), "worksheet": settings.google_sheets_worksheet}
