from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.core.schemas import Email


class UserBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str | None  # members the roster has no email for
    full_name: str
    department: str | None
    mtr_id: str | None = None


class LevelBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    rank: int
    name: str


class MemberProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    mtr_id: str | None = None
    national_id: str | None = None
    birthday: date | None = None
    university: str | None = None
    college: str | None = None
    major: str | None = None
    graduating_year: int | None = None
    phone: str | None = None
    guardian_phone: str | None = None
    uni_id: str | None = None
    location: str | None = None
    guardian_kinship: str | None = None
    joined_at: datetime | None = None
    data_confidence: str | None = None


class MemberProfileIn(BaseModel):
    """Editable roster fields. Every field optional; only the ones the client
    sends are touched (partial update). Sending null clears a field."""

    mtr_id: str | None = None
    national_id: str | None = None
    birthday: date | None = None
    university: str | None = None
    college: str | None = None
    major: str | None = None
    graduating_year: int | None = None
    phone: str | None = None
    guardian_phone: str | None = None
    uni_id: str | None = None
    location: str | None = None


class SelfProfileIn(BaseModel):
    """Roster fields a member may edit about themselves from the profile page.
    Excludes `mtr_id` on purpose — the org-assigned identifier is not
    self-editable. Full replace of the sent fields (missing -> cleared)."""

    national_id: str | None = None
    birthday: date | None = None
    university: str | None = None
    college: str | None = None
    major: str | None = None
    graduating_year: int | None = None
    phone: str | None = None
    guardian_phone: str | None = None
    uni_id: str | None = None
    location: str | None = None


class MeOut(UserBrief):
    manager_id: int | None
    level: LevelBrief | None  # strongest held level (a label; privileges add up)
    levels: list[str] = []  # every held level, strongest first
    privileges: list[str]  # union of every held level's privileges
    has_team: bool
    google_linked: bool
    created_at: datetime
    seats: list[str] = []  # org positions occupied — shown on the profile page
    profile: MemberProfileOut | None = None  # the person's roster fields


class UserAdminOut(UserBrief):
    manager_id: int | None
    is_active: bool
    google_linked: bool
    created_at: datetime
    access_level_id: int | None = None  # the personal override (may be None)
    effective_level: str | None = None  # computed: strongest of seats + override
    effective_rank: int | None = None
    levels: list[str] = []  # every level held (seats + override) — privileges add up
    seats: list[str] = []  # titles of org positions occupied — the org's reflection
    claimed: bool = True  # False until the owner sets the account up (see User.claimed)
    # the person's roster fields (biographical/contact) — the management view
    # doubles as the member directory
    profile: MemberProfileOut | None = None


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
    # Roster fields. Present -> the sent ones are set on the person.
    profile: MemberProfileIn | None = None
