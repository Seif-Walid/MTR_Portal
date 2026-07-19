import json

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AccessLevel(Base):
    """One rung of the access ladder — pure data, admin-editable on the site.

    `rank` is globally unique and ordered 1..N with 1 the strongest ("access
    level 1 is admin power"). A person's effective level is the strongest
    (lowest rank) among the levels of the org seats they occupy plus their
    personal override (users.access_level_id); with neither, they get the
    bottom-most level — the ladder's default tier, i.e. "guests".

    `privileges` is a JSON list of keys from access.service.PRIVILEGES — the
    fixed vocabulary of what the code can actually gate. The rank-1 level
    always behaves as if it holds every privilege regardless of what's
    stored, so an admin can never toggle themselves out of the controls
    (see access.service.privileges_of)."""

    __tablename__ = "access_levels"

    id: Mapped[int] = mapped_column(primary_key=True)
    rank: Mapped[int] = mapped_column(Integer, unique=True)
    name: Mapped[str] = mapped_column(String(100))
    privileges: Mapped[str] = mapped_column(Text, default="[]")  # JSON list of keys

    @property
    def privilege_keys(self) -> set[str]:
        return set(json.loads(self.privileges or "[]"))
