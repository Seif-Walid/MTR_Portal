from datetime import datetime, timezone
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class RoleSlug(StrEnum):
    ADMIN = "admin"
    CEO = "ceo"
    CTO = "cto"
    CFO = "cfo"
    SOFTWARE_LEAD = "software_lead"
    MECHANICAL_LEAD = "mechanical_lead"
    ELECTRICAL_LEAD = "electrical_lead"
    MEDIA_MANAGER = "media_manager"
    PROJECT_MANAGER = "project_manager"
    TEAM_LEAD = "team_lead"
    EMPLOYEE = "employee"
    STUDENT = "student"
    COMPETITION_MEMBER = "competition_member"


# Roles a request can be addressed to. Everyone except students, competition
# members and the technical admin (who sits outside the hierarchy).
NON_STAFF_ROLES = {RoleSlug.ADMIN, RoleSlug.STUDENT, RoleSlug.COMPETITION_MEMBER}


class Department(StrEnum):
    SOFTWARE = "software"
    MECHANICAL = "mechanical"
    ELECTRICAL = "electrical"
    MEDIA = "media"
    FINANCE = "finance"


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    is_staff: Mapped[bool] = mapped_column(Boolean, default=True)


class UserRole(Base):
    __tablename__ = "user_roles"
    __table_args__ = (UniqueConstraint("user_id", "role_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id", ondelete="CASCADE"))


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(255))
    hashed_password: Mapped[str] = mapped_column(String(255))
    department: Mapped[str | None] = mapped_column(String(50), nullable=True)
    manager_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    manager: Mapped["User | None"] = relationship(remote_side=[id])
    roles: Mapped[list[Role]] = relationship(secondary="user_roles", lazy="selectin")

    @property
    def role_slugs(self) -> set[str]:
        return {r.slug for r in self.roles}

    @property
    def is_admin(self) -> bool:
        return RoleSlug.ADMIN in self.role_slugs

    @property
    def is_staff(self) -> bool:
        """Union across roles: staff if any held role is a staff role."""
        return any(r.is_staff for r in self.roles)
