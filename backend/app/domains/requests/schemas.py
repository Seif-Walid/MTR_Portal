from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.domains.tasks.models import TaskPriority
from app.domains.users.schemas import UserBrief


class RequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    requester: UserBrief
    recipient: UserBrief
    title: str
    description: str
    priority: str
    due_date: date | None
    status: str
    decline_reason: str | None
    created_task_id: int | None
    created_at: datetime
    resolved_at: datetime | None
    created_task_status: str | None = None


class RequestCreate(BaseModel):
    recipient_id: int
    title: str = Field(min_length=1, max_length=255)
    description: str = ""
    priority: TaskPriority = TaskPriority.MEDIUM
    due_date: date | None = None


class RequestAccept(BaseModel):
    # None = the recipient takes the task themselves; otherwise delegate into
    # the recipient's own subtree.
    assignee_id: int | None = None


class RequestDecline(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)
