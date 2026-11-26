from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domains.users.schemas import UserBrief


class PositionNode(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    is_technical: bool
    on_website: bool = True
    parent_id: int | None
    access_level_id: int | None = None
    occupants: list[UserBrief] = []
    role_template_id: int | None = None
    children: list["PositionNode"] = []


PositionNode.model_rebuild()


class PositionCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    parent_id: int | None = None
    is_technical: bool = False
    on_website: bool = Field(default=True, description="Listed on the public website's People page.")
    access_level_id: int | None = Field(default=None, description="Access level this seat gives whoever holds it; omit for none.")
    occupant_ids: list[int] = []


class PositionEdit(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    is_technical: bool | None = None
    on_website: bool | None = None
    parent_id: int | None = Field(default=None, description="Move the position under this parent.")
    occupant_ids: list[int] | None = Field(default=None, description="REPLACES the whole occupant list: include everyone who should keep the seat, not only people being added.")
    access_level_id: int | None = None
    clear_access_level: bool = False


class RoleTemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title_template: str
    event: str
    sort_order: int
    access_level_id: int | None = None
    event_kind_id: int | None = None  # None = fires for every event kind
    parent_template_id: int | None = None


class RoleTemplateCreate(BaseModel):
    title_template: str = Field(min_length=1, max_length=255)
    event: Literal["event_created", "team_created", "team_member_added"] = Field(description="Which trigger creates the seat.")
    access_level_id: int | None = Field(default=None, description="Access level the produced seats give.")
    event_kind_id: int | None = Field(default=None, description="Only fire for events of this kind; omit for every kind.")
    insert_after_id: int | None = Field(default=None, description="Chain right after this template instead of at the end.")


class RoleTemplateEdit(BaseModel):
    title_template: str | None = Field(default=None, min_length=1, max_length=255)
    event: Literal["event_created", "team_created", "team_member_added"] | None = Field(default=None, description="Which trigger creates the seat.")
    access_level_id: int | None = None
    clear_access_level: bool = False
    sort_order: int | None = None
    event_kind_id: int | None = Field(default=None, description="Event kind to fire for; null = every kind. Only applied when set_event_kind is true.")
    set_event_kind: bool = Field(default=False, description="Must be true for event_kind_id to change (including setting it to null = every kind).")


class RoleRootOut(BaseModel):
    root_position_id: int | None
    has_templates: bool


class OccupantsSet(BaseModel):
    user_ids: list[int] = []


class EntityRoleOut(BaseModel):
    """One entity's occupancy of one role template — what a event/team
    "Roles" panel renders, regardless of what roles are actually configured."""

    template_id: int
    title: str
    position_id: int | None
    occupants: list[UserBrief] = []
