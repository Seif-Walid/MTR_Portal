"""Courses: a self-contained bundle of teaching material (HTML decks, chapters,
task sheets — whatever the course author built) stored in the database, plus
the catalogue that sorts its viewable documents into the fixed shelves every
course has: slides, book, tasks, task answers, and tools for everything else.

The bundle lives in `course_files` rather than on disk so it survives
redeploys and travels with the database (backups, db_copy) like everything
else. Its pages link to each other and to shared CSS/JS by relative path, so
the portal serves the bundle verbatim under one URL prefix and the links keep
working untouched."""

from datetime import datetime, timezone
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class MaterialKind(StrEnum):
    SLIDES = "slides"
    BOOK = "book"
    TASKS = "tasks"
    ANSWERS = "answers"
    TOOLS = "tools"


class Course(Base):
    __tablename__ = "courses"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The card cover: an image from the bundle when set, otherwise a gradient
    # in `accent` with `cover_label` set large across it.
    cover_label: Mapped[str | None] = mapped_column(String(40), nullable=True)
    accent: Mapped[str] = mapped_column(String(20), default="#5cc6ff")
    cover_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_published: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    materials: Mapped[list["CourseMaterial"]] = relationship(
        back_populates="course", cascade="all, delete-orphan", passive_deletes=True
    )


class CourseFile(Base):
    """One file of the bundle, addressed by its path inside the bundle."""

    __tablename__ = "course_files"
    __table_args__ = (UniqueConstraint("course_id", "path"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    path: Mapped[str] = mapped_column(String(500))
    media_type: Mapped[str] = mapped_column(String(100))
    size: Mapped[int] = mapped_column(Integer)
    content: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)


class CourseMaterial(Base):
    """One item on one of the course's shelves: a file of the course (from the
    bundle, or uploaded straight onto the shelf) or, when `external_url` is
    set instead of `path`, a link to something hosted elsewhere. `unit` groups materials that belong together (week 3's slides, chapter,
    tasks and answers); `is_released` holds a document back from learners —
    task answers start held back."""

    __tablename__ = "course_materials"
    __table_args__ = (UniqueConstraint("course_id", "path"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(String(300))
    path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # A cached PDF rendition of an office file (its `_previews/….pdf` path), so
    # the viewer can show it inline; NULL when the file needs no rendition.
    preview_path: Mapped[str | None] = mapped_column(String(600), nullable=True)
    external_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    unit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    unit_label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_released: Mapped[bool] = mapped_column(Boolean, default=True)

    course: Mapped[Course] = relationship(back_populates="materials")


class CourseProgress(Base):
    """A learner ticked a material off."""

    __tablename__ = "course_progress"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    material_id: Mapped[int] = mapped_column(
        ForeignKey("course_materials.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
