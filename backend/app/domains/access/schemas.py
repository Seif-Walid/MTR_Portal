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
    rank: int | None = Field(default=None, description="1-based place in the ladder (1 = most powerful); omit to append at the bottom.")


class LevelEdit(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    privileges: list[str] | None = Field(default=None, description="Replaces the whole privilege list.")
    rank: int | None = Field(default=None, description="1-based place in the ladder (1 = most powerful).")
