from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.domains.competitions.models import CompetitionStatus
from app.domains.users.schemas import UserBrief


class CategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class MemberOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int  # membership row id
    user: UserBrief


class CompetitionBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    status: str
    category: CategoryOut | None = None


class CompetitionOut(CompetitionBrief):
    start_date: date | None
    end_date: date | None
    notes: str
    team_name: str | None
    team_lead: UserBrief | None
    member_count: int = 0
    allocation_count: int = 0
    created_at: datetime


class CompetitionDetailOut(CompetitionOut):
    members: list[MemberOut] = []


class CompetitionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    category_id: int | None = None
    start_date: date | None = None
    end_date: date | None = None
    team_name: str | None = Field(default=None, max_length=255)
    team_lead_id: int | None = None
    notes: str = ""


class CompetitionEdit(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    category_id: int | None = None
    clear_category: bool = False
    start_date: date | None = None
    end_date: date | None = None
    clear_start_date: bool = False
    clear_end_date: bool = False
    team_name: str | None = Field(default=None, max_length=255)
    team_lead_id: int | None = None
    clear_team_lead: bool = False
    status: CompetitionStatus | None = None
    notes: str | None = None


class MemberAdd(BaseModel):
    user_id: int
