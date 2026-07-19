from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.core.schemas import Email


class UserBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    full_name: str
    department: str | None


class LevelBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    rank: int
    name: str


class MeOut(UserBrief):
    manager_id: int | None
    level: LevelBrief | None  # effective level (strongest of seats + override)
    privileges: list[str]
    has_team: bool
    google_linked: bool


class UserAdminOut(UserBrief):
    manager_id: int | None
    is_active: bool
    google_linked: bool
    created_at: datetime
    access_level_id: int | None = None  # the personal override (may be None)
    effective_level: str | None = None  # computed: strongest of seats + override
    effective_rank: int | None = None
    seats: list[str] = []  # titles of org positions occupied — the org's reflection


class UserCreate(BaseModel):
    email: Email
    full_name: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=8, max_length=128)
    access_level_id: int | None = None


class UserUpdate(BaseModel):
    # No manager here on purpose: who reports to whom comes solely from the
    # Organization chart (positions → resync_managers), never a field here.
    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    password: str | None = Field(default=None, min_length=8, max_length=128)
    is_active: bool | None = None
    access_level_id: int | None = None
    clear_access_level: bool = False
