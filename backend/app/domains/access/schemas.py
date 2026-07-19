from pydantic import BaseModel, Field


class PrivilegeOut(BaseModel):
    key: str
    label: str


class LevelOut(BaseModel):
    id: int
    rank: int
    name: str
    privileges: list[str]
    is_top: bool  # rank 1 — always holds every privilege, not editable


class LevelCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    privileges: list[str] = []
    rank: int | None = None  # 1-based position in the ladder; appended if omitted


class LevelEdit(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    privileges: list[str] | None = None
    rank: int | None = None
