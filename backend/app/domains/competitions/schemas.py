from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.domains.competitions.models import CompetitionStatus
from app.domains.users.schemas import UserBrief


class MemberOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user: UserBrief


class TeamOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    lead: UserBrief | None
    members: list[MemberOut] = []
    can_manage_members: bool = False  # for the current user


class CategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    teams: list[TeamOut] = []


class CompetitionBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    status: str


class CompetitionOut(CompetitionBrief):
    description: str
    start_date: date | None
    end_date: date | None
    created_at: datetime
    pms: list[UserBrief] = []
    category_count: int = 0
    team_count: int = 0
    member_count: int = 0
    allocation_count: int = 0
    can_manage: bool = False  # for the current user


class CompetitionDetailOut(CompetitionOut):
    categories: list[CategoryOut] = []


class CompetitionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = ""
    start_date: date | None = None
    end_date: date | None = None


class CompetitionEdit(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    clear_start_date: bool = False
    clear_end_date: bool = False
    status: CompetitionStatus | None = None


class PMAdd(BaseModel):
    user_id: int


class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class TeamCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    lead_id: int | None = None


class TeamEdit(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    lead_id: int | None = None
    clear_lead: bool = False


class MemberAdd(BaseModel):
    user_id: int
