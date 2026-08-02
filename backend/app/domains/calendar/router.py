from datetime import date

from fastapi import APIRouter

from app.domains.auth.deps import DB, CurrentUser
from app.domains.calendar import service
from app.domains.calendar.schemas import CalendarItem

router = APIRouter(prefix="/calendar", tags=["calendar"])


@router.get("")
def calendar(
    db: DB,
    user: CurrentUser,
    scope: str = "general",
    sources: str = "tasks",
    start: date | None = None,
    end: date | None = None,
) -> list[CalendarItem]:
    """Dated items for the calendar. `scope` is 'general' (everything you can
    see) or 'me' (only what you participate in). `sources` is a comma-list of
    tasks|events|inventory|requests. `start`/`end` bound the window (the
    visible month range); omit for no bound. Sources you can't view are
    silently skipped."""
    wanted = [s for s in (sources.split(",") if sources else []) if s in service.SOURCES]
    return service.gather(db, user, scope=scope, sources=wanted, start=start, end=end)
