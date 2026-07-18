from pydantic import BaseModel, ConfigDict, Field

from app.domains.users.schemas import UserBrief


class PositionNode(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    is_technical: bool
    parent_id: int | None
    occupants: list[UserBrief] = []
    role_template_id: int | None = None
    children: list["PositionNode"] = []


PositionNode.model_rebuild()


class PositionCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    parent_id: int | None = None
    is_technical: bool = False
    occupant_ids: list[int] = []


class PositionEdit(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    is_technical: bool | None = None
    parent_id: int | None = None  # reparent
    occupant_ids: list[int] | None = None  # replaces the whole occupant list


class RoleTemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title_template: str
    event: str
    sort_order: int
    grants_management: bool
    auto_assign_creator: bool
    parent_template_id: int | None = None


class RoleTemplateCreate(BaseModel):
    title_template: str = Field(min_length=1, max_length=255)
    event: str
    grants_management: bool = False
    auto_assign_creator: bool = False
    insert_after_id: int | None = None  # chain right after this template, not at the end


class RoleTemplateEdit(BaseModel):
    title_template: str | None = Field(default=None, min_length=1, max_length=255)
    grants_management: bool | None = None
    auto_assign_creator: bool | None = None
    sort_order: int | None = None


class RoleRootOut(BaseModel):
    root_position_id: int | None
    has_templates: bool


class OccupantsSet(BaseModel):
    user_ids: list[int] = []


class EntityRoleOut(BaseModel):
    """One entity's occupancy of one role template — what a competition/team
    "Roles" panel renders, regardless of what roles are actually configured."""

    template_id: int
    title: str
    position_id: int | None
    occupants: list[UserBrief] = []
