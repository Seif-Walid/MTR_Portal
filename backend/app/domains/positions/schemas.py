from pydantic import BaseModel, ConfigDict, Field

from app.domains.users.schemas import UserBrief


class PositionNode(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    is_technical: bool
    parent_id: int | None
    occupant: UserBrief | None
    children: list["PositionNode"] = []


PositionNode.model_rebuild()


class PositionCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    parent_id: int | None = None
    is_technical: bool = False
    occupant_id: int | None = None


class PositionEdit(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    is_technical: bool | None = None
    parent_id: int | None = None  # reparent
    occupant_id: int | None = None  # assign occupant
    clear_occupant: bool = False
