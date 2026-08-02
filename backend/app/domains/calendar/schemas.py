from datetime import date

from pydantic import BaseModel


class CalendarItem(BaseModel):
    """One dated thing on the calendar. `source` tells the frontend which
    filter it belongs to and how to link it; `start`/`end` bound it (end is
    None for single-day items, set only for multi-day event spans)."""

    source: str  # "task" | "event" | "inventory" | "request"
    id: int
    title: str
    start: date
    end: date | None = None
    kind: str | None = None  # event-kind name, task/request status, or "needed"/"return"
    detail: str | None = None
    overdue: bool = False
