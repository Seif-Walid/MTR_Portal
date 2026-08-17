from datetime import date

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


class TimeBlockCreate(BaseModel):
    team_type: str = Field(pattern="^(event|org)$")
    event_team_id: int | None = None
    position_id: int | None = None
    title: str = Field(default="", max_length=255)
    start_date: date
    end_date: date
    weekday_mask: int = Field(default=0, ge=0, le=127)


class TimeBlockEdit(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    start_date: date | None = None
    end_date: date | None = None
    weekday_mask: int | None = Field(default=None, ge=0, le=127)
