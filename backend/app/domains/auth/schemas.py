from pydantic import BaseModel, Field

from app.core.schemas import Email


class LoginIn(BaseModel):
    email: Email
    password: str


class RegisterIn(BaseModel):
    email: Email
    full_name: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=8, max_length=128)


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)
