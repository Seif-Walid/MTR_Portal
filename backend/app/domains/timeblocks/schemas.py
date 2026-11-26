from datetime import date, time

from pydantic import BaseModel, ConfigDict, Field


class TimeBlockOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    team_type: str  # "event" | "org"
    event_team_id: int | None
    position_id: int | None
    title: str
    start_date: date
    end_date: date
    weekday_mask: int  # 0 = whole span; else bit i (Mon=0..Sun=6)
    start_time: time | None = None  # both None = all-day
    end_time: time | None = None


class TimeBlockCreate(BaseModel):
    team_type: str = Field(pattern="^(event|org)$")
    event_team_id: int | None = None
    position_id: int | None = None
    title: str = Field(default="", max_length=255)
    start_date: date
    end_date: date
    weekday_mask: int = Field(default=0, ge=0, le=127, description=(
        "Which weekdays the block repeats on. 0 = every day of the span. "
        "Otherwise a bitmask with Monday=1, Tuesday=2, Wednesday=4, Thursday=8, "
        "Friday=16, Saturday=32, Sunday=64 (add bits to combine; e.g. Thursday "
        "only = 8, Sunday+Wednesday = 68)."
    ))
    start_time: time | None = Field(default=None, description="Local time of day (HH:MM) the block starts on each day; omit both times for all-day.")
    end_time: time | None = Field(default=None, description="Local time of day the block ends; give with start_time or omit both.")


class TimeBlockEdit(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    start_date: date | None = None
    end_date: date | None = None
    weekday_mask: int | None = Field(default=None, ge=0, le=127, description=(
        "Which weekdays the block repeats on. 0 = every day of the span. "
        "Otherwise a bitmask with Monday=1, Tuesday=2, Wednesday=4, Thursday=8, "
        "Friday=16, Saturday=32, Sunday=64 (add bits to combine; e.g. Thursday "
        "only = 8, Sunday+Wednesday = 68)."
    ))
    # times are always sent together; clearing both makes the block all-day
    start_time: time | None = None
    end_time: time | None = None
