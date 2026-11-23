from pydantic import BaseModel, Field

from app.core.schemas import Email


class LoginIn(BaseModel):
    email: Email
    password: str


class RequestEntryIn(BaseModel):
    """"Request entry" on the sign-in page. A member an admin already added
    only needs email + password (that activates their account); anyone else
    files a request, so the contact details are asked for too."""

    email: Email
    full_name: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=8, max_length=128)
    phone: str | None = Field(default=None, max_length=50)
    school: str | None = Field(default=None, max_length=255)
    year: str | None = Field(default=None, max_length=100)
    why: str | None = Field(default=None, max_length=2000)


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


class ForgotPasswordIn(BaseModel):
    email: Email


class ResetPasswordIn(BaseModel):
    token: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)
