from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.domains.events.models import EventStatus
from app.domains.positions.schemas import EntityRoleOut
from app.domains.users.schemas import UserBrief


class EventKindOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    name: str
    event_label: str
    category_label: str
    team_label: str
    member_label: str
    sort_order: int


class EventKindCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    event_label: str = Field(min_length=1, max_length=100)
    category_label: str = Field(default="Category", min_length=1, max_length=100)
    team_label: str = Field(default="Team", min_length=1, max_length=100)
    member_label: str = Field(default="Member", min_length=1, max_length=100)


class EventKindEdit(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    event_label: str | None = Field(default=None, min_length=1, max_length=100)
    category_label: str | None = Field(default=None, min_length=1, max_length=100)
    team_label: str | None = Field(default=None, min_length=1, max_length=100)
    member_label: str | None = Field(default=None, min_length=1, max_length=100)


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


class EventBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    status: str


class EventOut(EventBrief):
    description: str
    start_date: date | None
    end_date: date | None
    created_at: datetime
    kind: EventKindOut | None = None
    roles: list[EntityRoleOut] = []
    category_count: int = 0
    team_count: int = 0
    member_count: int = 0
    allocation_count: int = 0
    can_manage: bool = False  # for the current user


class EventDetailOut(EventOut):
    categories: list[CategoryOut] = []


class EventCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    kind_id: int | None = None  # which event kind; defaults to Event
    description: str = ""
    start_date: date | None = None
    end_date: date | None = None
    # Where the very first role-template position ever goes in the org
    # chart. Only required if that hasn't happened yet at all, system-wide
    # (see GET /org/roles/root) — ignored after that, since the first
    # answer is remembered.
    role_root_position_id: int | None = None


class EventEdit(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    clear_start_date: bool = False
    clear_end_date: bool = False
    status: EventStatus | None = None


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
