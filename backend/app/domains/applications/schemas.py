import re
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.core.schemas import Email
from app.domains.applications.models import ApplicationStatus


def _clean(v: str | None) -> str | None:
    if v is None:
        return None
    v = re.sub(r"\s+", " ", v).strip()
    return v or None


class ApplicationIn(BaseModel):
    """What the website's join form posts. Field names match the form's own
    `name` attributes so the site can send its FormData as-is."""

    name: str = Field(min_length=2, max_length=255)
    email: Email = Field(max_length=255)
    phone: str = Field(max_length=50)
    school: str = Field(min_length=2, max_length=255)
    year: str = Field(min_length=1, max_length=100)
    subteam: str | None = Field(default=None, max_length=50)
    why: str = Field(min_length=20, max_length=2000)
    # Honeypot: hidden on the form, so only bots fill it in.
    website: str | None = Field(default=None, max_length=255)

    @field_validator("name", "school", "year", "subteam", mode="before")
    @classmethod
    def _squash(cls, v):
        return _clean(v) if isinstance(v, str) else v

    @field_validator("why", mode="before")
    @classmethod
    def _strip(cls, v):
        return v.strip() if isinstance(v, str) else v

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str) -> str:
        v = v.strip()
        if not 8 <= len(re.sub(r"\D", "", v)) <= 15:
            raise ValueError("Enter a phone number we can reach on WhatsApp")
        return v

    @field_validator("subteam")
    @classmethod
    def _subteam(cls, v: str | None) -> str | None:
        return v.lower() if v else None


class ApplicationPatch(BaseModel):
    status: ApplicationStatus | None = None
    notes: str | None = None


class RosterMatch(BaseModel):
    id: int
    mtr_id: str | None
    name: str
    matched_on: list[str]


class ApplicationOut(BaseModel):
    id: int
    full_name: str
    email: str
    phone: str
    school: str
    year: str
    subteam: str | None
    motivation: str
    status: ApplicationStatus
    notes: str | None
    member_id: int | None
    member_mtr_id: str | None
    reviewed_by: str | None
    reviewed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    # Who on the roster already shares this applicant's email or phone —
    # someone re-applying, or already a member.
    roster_matches: list[RosterMatch]
