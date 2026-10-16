"""Read endpoints for the finance books' computed views. Every stored table is
edited through the bulk-editor grid (see bulk/registry.py — gated by
finance.edit); these return what the spreadsheet used to compute."""

from fastapi import APIRouter, HTTPException, status

from app.domains.access import service as access
from app.domains.auth.deps import DB, CurrentUser
from app.domains.finance import service
from app.domains.finance.models import FinanceSeason

router = APIRouter(prefix="/finance", tags=["finance"])


def _season_or_current(db: DB, season_id: int | None) -> FinanceSeason:
    season = db.get(FinanceSeason, season_id) if season_id is not None else service.current_season(db)
    if season is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such season")
    return season


@router.get("/seasons")
def list_seasons(db: DB, user: CurrentUser) -> dict:
    access.require_privilege(db, user, "finance.view")
    current = service.current_season(db)
    return {
        "seasons": [service._season_out(s) for s in service.seasons(db)],
        "current_id": current.id if current else None,
    }


@router.get("/dashboard")
def dashboard(db: DB, user: CurrentUser, season_id: int | None = None) -> dict:
    """Roll-up of the books. Omit season_id for every season together."""
    access.require_privilege(db, user, "finance.view")
    if season_id is not None and db.get(FinanceSeason, season_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such season")
    return service.dashboard(db, season_id)


@router.get("/dues")
def dues(db: DB, user: CurrentUser, season_id: int | None = None) -> dict:
    """The season's dues roster with the monthly payment grid and projection."""
    access.require_privilege(db, user, "finance.view")
    return service.dues_ledger(db, _season_or_current(db, season_id))


@router.get("/cash")
def cash(db: DB, user: CurrentUser) -> dict:
    access.require_privilege(db, user, "finance.view")
    return service.cash_balances(db)


@router.get("/events/{event_id}")
def event_money(event_id: int, db: DB, user: CurrentUser) -> dict:
    access.require_privilege(db, user, "finance.view")
    return service.event_money(db, event_id)
