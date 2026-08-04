from datetime import date

from pydantic import BaseModel


class DashboardItem(BaseModel):
    source: str  # task | request | inventory | event
    id: int
    title: str
    detail: str | None = None  # subtitle: counterparty / context
    due: date | None = None
    overdue: bool = False
    blocked: bool = False
    status: str | None = None  # raw task/request status, rendered monochrome
    priority: str | None = None
    action: str = "Open"  # the verb this row invites


class DashboardSection(BaseModel):
    key: str  # overdue | review | waiting | today | week
    label: str
    tone: str  # "danger" | "normal"
    count: int  # full size of the bucket (may exceed len(items))
    items: list[DashboardItem]


class DashboardStat(BaseModel):
    key: str
    label: str
    count: int
    tone: str  # "danger" | "normal"


class Dashboard(BaseModel):
    as_of: date
    greeting_name: str
    is_reviewer: bool
    all_clear: bool
    stats: list[DashboardStat]
    sections: list[DashboardSection]
