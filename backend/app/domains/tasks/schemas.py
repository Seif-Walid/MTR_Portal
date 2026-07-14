from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.domains.tasks.models import TaskPriority, TaskStatus
from app.domains.users.schemas import UserBrief


class AttachmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    content_type: str
    size: int
    uploaded_by_id: int
    created_at: datetime


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: str
    assigner: UserBrief
    assignee: UserBrief
    due_date: date | None
    priority: str
    category: str | None
    status: str
    origin_request_id: int | None
    created_at: datetime
    updated_at: datetime
    attachments: list[AttachmentOut] = []


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = ""
    assignee_id: int
    due_date: date | None = None
    priority: TaskPriority = TaskPriority.MEDIUM
    category: str | None = Field(default=None, max_length=100)


class TaskEdit(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    due_date: date | None = None
    clear_due_date: bool = False
    priority: TaskPriority | None = None
    category: str | None = Field(default=None, max_length=100)


class StatusChange(BaseModel):
    status: TaskStatus
