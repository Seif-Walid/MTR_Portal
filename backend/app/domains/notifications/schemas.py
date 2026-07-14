from datetime import datetime

from pydantic import BaseModel, ConfigDict


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
    ids: list[int] | None = None  # None = mark all read
