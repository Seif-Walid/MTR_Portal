from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.core.schemas import Email
from app.domains.users.models import Department, RoleSlug


class RoleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    slug: str
    name: str
    is_staff: bool


class UserBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    full_name: str
    department: str | None
    roles: list[RoleOut]


class MeOut(UserBrief):
    manager_id: int | None
    is_admin: bool
    is_staff: bool
    has_team: bool


class UserAdminOut(UserBrief):
    manager_id: int | None
    is_active: bool
    created_at: datetime


class UserCreate(BaseModel):
    email: Email
    full_name: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=8, max_length=128)
    roles: list[RoleSlug] = Field(min_length=1)
    department: Department | None = None
    manager_id: int | None = None


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    password: str | None = Field(default=None, min_length=8, max_length=128)
    roles: list[RoleSlug] | None = Field(default=None, min_length=1)
    department: Department | None = None
    clear_department: bool = False
    manager_id: int | None = None
    clear_manager: bool = False
    is_active: bool | None = None
