from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    type: str
    message: str
    task_id: int | None
    request_id: int | None
    is_read: bool
    created_at: datetime


class MarkReadIn(BaseModel):
    ids: list[int] | None = Field(default=None, description="Notifications to mark read. Omitted or null marks EVERY notification read.")


class PushKeysIn(BaseModel):
    p256dh: str = Field(max_length=200)
    auth: str = Field(max_length=100)


class PushSubscribeIn(BaseModel):
    endpoint: str = Field(max_length=2000)
    keys: PushKeysIn


class PushEndpointIn(BaseModel):
    endpoint: str = Field(max_length=2000)


class PushDeviceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    device: str
    created_at: datetime
    last_used_at: datetime | None
