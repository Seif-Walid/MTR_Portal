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


class TaskCommentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    author: UserBrief
    body: str
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
    is_blocked: bool
    blocked_reason: str
    batch_id: str | None
    event_team_id: int | None
    event_team_name: str | None = None
    team_visible: bool
    created_at: datetime
    updated_at: datetime
    attachments: list[AttachmentOut] = []
    comments: list[TaskCommentOut] = []


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = ""
    # explicit people to assign to
    assignee_ids: list[int] = Field(default_factory=list)
    # With assignee_ids: which team the task belongs to — the same person can
    # be on several teams, so the context is picked, not guessed (see
    # tasks/service.shared_team_options). Alone (no assignee_ids): assign to
    # the whole team, fanning out to every member the assigner may task.
    event_team_id: int | None = None
    # only meaningful with event_team_id: share the task with the whole team
    team_visible: bool = False
    due_date: date | None = None
    priority: TaskPriority = TaskPriority.MEDIUM
    category: str | None = Field(default=None, max_length=100)


class TeamOptionOut(BaseModel):
    """A team every selected assignee is on — the candidate contexts for a
    person-assigned task."""

    team_id: int
    name: str
    event_name: str
    category_name: str
    shared_with_me: bool


class TaskEdit(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    due_date: date | None = None
    clear_due_date: bool = False
    priority: TaskPriority | None = None
    category: str | None = Field(default=None, max_length=100)


class StatusChange(BaseModel):
    status: TaskStatus


class BlockedChange(BaseModel):
    is_blocked: bool
    reason: str = Field(default="", max_length=500)


class TaskCommentCreate(BaseModel):
    body: str = Field(min_length=1, max_length=4000)


class TaskHistoryEntryOut(BaseModel):
    actor: str
    action: str
    detail: str  # JSON string
    created_at: datetime
