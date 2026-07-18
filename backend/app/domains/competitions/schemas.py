from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.domains.competitions.models import CompetitionStatus
from app.domains.positions.schemas import EntityRoleOut
from app.domains.users.schemas import UserBrief


class MemberOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user: UserBrief


class TeamOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    roles: list[EntityRoleOut] = []
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
    roles: list[EntityRoleOut] = []
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
    # Where the very first role-template position ever goes in the org
    # chart. Only required if that hasn't happened yet at all, system-wide
    # (see GET /org/roles/root) — ignored after that, since the first
    # answer is remembered.
    role_root_position_id: int | None = None


class CompetitionEdit(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    clear_start_date: bool = False
    clear_end_date: bool = False
    status: CompetitionStatus | None = None


class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class TeamCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    role_root_position_id: int | None = None


class TeamEdit(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)


class MemberAdd(BaseModel):
    user_id: int
    role_root_position_id: int | None = None
