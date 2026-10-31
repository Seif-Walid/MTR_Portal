from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class MemberRow(BaseModel):
    """One roster line in the members directory (no sensitive fields)."""

    id: int
    mtr_id: str | None
    name: str
    email: str | None
    phone: str | None
    university: str | None
    college: str | None
    major: str | None
    graduating_year: int | None
    location: str | None
    joined_at: datetime | None
    data_confidence: str | None
    claimed: bool  # account set up: a password or a linked Google identity
    is_active: bool
    events: list[str]  # event codes/names this member took part in


class ParticipationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    event_id: int
    event_name: str
    event_code: str | None
    event_kind: str | None
    event_start: date | None
    role: str | None
    team: str | None
    mentor: str | None
    rating: str | None
    registered_at: datetime | None


class MemberDetail(MemberRow):
    full_name: str | None
    national_id: str | None
    birthday: date | None
    guardian_phone: str | None
    guardian_kinship: str | None
    uni_id: str | None
    source_records: int | None
    review_note: str | None
    participations: list[ParticipationOut]


class MemberIn(BaseModel):
    """Create / edit a member (their account). On edit only the sent fields change."""

    full_name: str | None = Field(default=None, max_length=255)
    email: str | None = Field(default=None, max_length=255)
    mtr_id: str | None = Field(default=None, max_length=20)
    phone: str | None = None
    national_id: str | None = None
    birthday: date | None = None
    location: str | None = None
    university: str | None = None
    college: str | None = None
    major: str | None = None
    uni_id: str | None = None
    graduating_year: int | None = None
    guardian_phone: str | None = None
    guardian_kinship: str | None = None
    joined_at: datetime | None = None
    data_confidence: str | None = None
    review_note: str | None = None


class DuplicateCheckIn(BaseModel):
    name: str | None = None
    phone: str | None = None
    email: str | None = None
    exclude_id: int | None = None


class DuplicateHit(BaseModel):
    id: int
    mtr_id: str | None
    name: str
    matched_on: list[str]
