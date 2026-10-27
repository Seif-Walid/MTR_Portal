"""The Google Drive account the portal stores big uploads in (task
submissions: CAD assemblies and the like). One connection for the whole
portal — whichever club account an admin connects owns every file."""

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class DriveConnection(Base):
    __tablename__ = "drive_connections"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255))
    # Long-lived OAuth refresh token for the drive.file scope: the portal can
    # only ever see the files it created itself, nothing else in that Drive.
    refresh_token: Mapped[str] = mapped_column(Text)
    root_folder_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    connected_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    connected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
