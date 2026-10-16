"""Courses: the catalogue, the course page's shelves, the bundle's files, and
each learner's ticks. Viewing is gated by courses.view; uploading bundles and
editing the shelves by courses.manage. Held-back materials (task answers until
they're released) are refused to learners at the file level, not just hidden
from the list."""

from urllib.parse import quote

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.config import settings
from app.domains.access import service as access
from app.domains.audit.service import log as audit_log
from app.domains.auth.deps import DB, CurrentUser
from app.domains.courses import service
from app.domains.courses.models import Course, CourseFile, CourseMaterial, CourseProgress, MaterialKind

router = APIRouter(prefix="/courses", tags=["courses"])

HEX = r"^#[0-9a-fA-F]{6}$"


def _file_url(course_id: int, path: str) -> str:
    return f"/api/courses/{course_id}/files/{quote(path)}"


def _read_upload(file: UploadFile) -> bytes:
    limit = settings.max_upload_mb * 1024 * 1024
    data = file.file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            f"File exceeds {settings.max_upload_mb} MB limit")
    return data


def _course_out(course: Course, released: list[CourseMaterial], done: set[int]) -> dict:
    counts = {k.value: 0 for k in MaterialKind}
    for m in course.materials:
        counts[m.kind] = counts.get(m.kind, 0) + 1
    total = len(released)
    completed = sum(1 for m in released if m.id in done)
    return {
        "id": course.id,
        "title": course.title,
        "description": course.description,
        "cover_label": course.cover_label,
        "accent": course.accent,
        "cover_url": _file_url(course.id, course.cover_path) if course.cover_path else None,
        "cover_path": course.cover_path,
        "is_published": course.is_published,
        "sort_order": course.sort_order,
        "counts": counts,
        "total": total,
        "completed": completed,
        "percent": round(100 * completed / total) if total else 0,
        "updated_at": course.updated_at,
    }


def _material_out(m: CourseMaterial, done: set[int], manage: bool) -> dict:
    open_ = m.is_released or manage
    if m.external_url:
        url = m.external_url
    else:
        url = _file_url(m.course_id, m.path) if m.path else None
    return {
        "id": m.id,
        "kind": m.kind,
        "title": m.title,
        "path": m.path if manage else None,
        "is_link": bool(m.external_url),
        "media_type": service.media_type_of(m.path) if m.path else None,
        "unit": m.unit,
        "unit_label": m.unit_label,
        "sort_order": m.sort_order,
        "is_released": m.is_released,
        "url": url if open_ else None,
        "completed": m.id in done,
    }


def _released(course: Course) -> list[CourseMaterial]:
    return [m for m in course.materials if m.is_released]


@router.get("/kinds")
def kinds(db: DB, user: CurrentUser) -> list[dict]:
    access.require_privilege(db, user, "courses.view")
    return [{"key": k, "label": label} for k, label in service.KIND_LABEL.items()]


@router.get("")
def list_courses(db: DB, user: CurrentUser) -> list[dict]:
    access.require_privilege(db, user, "courses.view")
    manage = service.can_manage(db, user)
    q = select(Course).order_by(Course.sort_order, Course.id)
    if not manage:
        q = q.where(Course.is_published.is_(True))
    done = set(db.scalars(select(CourseProgress.material_id).where(CourseProgress.user_id == user.id)))
    return [_course_out(c, _released(c), done) for c in db.scalars(q)]


@router.get("/{course_id}")
def get_course(course_id: int, db: DB, user: CurrentUser) -> dict:
    course = service.visible_course(db, user, course_id)
    manage = service.can_manage(db, user)
    done = service.completed_ids(db, user, course.id)
    mats = sorted(course.materials, key=lambda m: (m.sort_order, m.id))
    out = _course_out(course, _released(course), done)
    out["materials"] = [_material_out(m, done, manage) for m in mats]
    out["can_manage"] = manage
    out["file_count"] = service.file_count(db, course.id) if manage else None
    return out


@router.post("", status_code=status.HTTP_201_CREATED)
def create_course(
    db: DB,
    user: CurrentUser,
    title: str = Form(..., min_length=1, max_length=200),
    bundle: UploadFile | None = File(None),
    description: str | None = Form(None),
    cover_label: str | None = Form(None, max_length=40),
    accent: str = Form("#5cc6ff", pattern=HEX),
) -> dict:
    """A course starts empty (its shelves are then filled one item at a time)
    or from a bundle zip."""
    access.require_privilege(db, user, "courses.manage")
    files = service.read_zip(_read_upload(bundle)) if bundle is not None else None
    order = (db.scalar(select(Course.sort_order).order_by(Course.sort_order.desc()).limit(1)) or 0) + 1
    course = Course(title=title.strip(), description=description or None,
                    cover_label=cover_label or None, accent=accent, sort_order=order)
    db.add(course)
    db.flush()
    summary = service.replace_bundle(db, course, files) if files else {"files": 0, "materials_added": 0, "materials_removed": 0}
    audit_log(db, user.id, "courses", "course_created", "course", course.id, {"title": course.title, **summary})
    db.commit()
    return {"id": course.id, **summary}


class CourseEdit(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = None
    cover_label: str | None = Field(None, max_length=40)
    accent: str | None = Field(None, pattern=HEX)
    cover_path: str | None = None
    is_published: bool | None = None
    sort_order: int | None = None


@router.patch("/{course_id}")
def edit_course(course_id: int, payload: CourseEdit, db: DB, user: CurrentUser) -> dict:
    access.require_privilege(db, user, "courses.manage")
    course = service.visible_course(db, user, course_id)
    changes = payload.model_dump(exclude_unset=True)
    if changes.get("cover_path"):
        exists = db.scalar(select(CourseFile.id).where(
            CourseFile.course_id == course.id, CourseFile.path == changes["cover_path"]))
        if exists is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "No such file in the bundle")
    for key, value in changes.items():
        if key in {"description", "cover_label", "cover_path"} and value == "":
            value = None
        if key == "title" and value is None:
            continue
        setattr(course, key, value)
    audit_log(db, user.id, "courses", "course_edited", "course", course.id, changes)
    db.commit()
    return {"ok": True}


@router.put("/{course_id}/bundle")
def upload_bundle(course_id: int, db: DB, user: CurrentUser, bundle: UploadFile = File(...)) -> dict:
    access.require_privilege(db, user, "courses.manage")
    course = service.visible_course(db, user, course_id)
    summary = service.replace_bundle(db, course, service.read_zip(_read_upload(bundle)))
    audit_log(db, user.id, "courses", "bundle_replaced", "course", course.id, summary)
    db.commit()
    return summary


@router.post("/{course_id}/cover")
def upload_cover(course_id: int, db: DB, user: CurrentUser, image: UploadFile = File(...)) -> dict:
    """Store a cover image alongside the bundle and point the card at it."""
    access.require_privilege(db, user, "courses.manage")
    course = service.visible_course(db, user, course_id)
    if not (image.content_type or "").startswith("image/"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The cover must be an image")
    data = _read_upload(image)
    path = f"{service.COVER_DIR}/{(image.filename or 'cover').rsplit('/', 1)[-1]}"
    row = db.scalar(select(CourseFile).where(CourseFile.course_id == course.id, CourseFile.path == path))
    if row is None:
        row = CourseFile(course_id=course.id, path=path)
        db.add(row)
    row.media_type, row.size, row.content = image.content_type, len(data), data
    course.cover_path = path
    db.commit()
    return {"cover_url": _file_url(course.id, path)}


@router.delete("/{course_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_course(course_id: int, db: DB, user: CurrentUser) -> None:
    access.require_privilege(db, user, "courses.manage")
    course = service.visible_course(db, user, course_id)
    audit_log(db, user.id, "courses", "course_deleted", "course", course.id, {"title": course.title})
    db.delete(course)
    db.commit()


def _check_url(url: str) -> str:
    url = url.strip()
    if not url.lower().startswith(("http://", "https://")) or len(url) > 1000:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Links must be http(s) URLs")
    return url


@router.post("/{course_id}/materials", status_code=status.HTTP_201_CREATED)
def add_material(
    course_id: int,
    db: DB,
    user: CurrentUser,
    kind: MaterialKind = Form(...),
    title: str | None = Form(None, max_length=300),
    unit_label: str | None = Form(None, max_length=100),
    file: UploadFile | None = File(None),
    url: str | None = Form(None),
) -> dict:
    """One file or one link onto a shelf."""
    access.require_privilege(db, user, "courses.manage")
    course = service.visible_course(db, user, course_id)
    if (file is None) == (not url):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Give either a file or a link")
    if file is not None:
        m = service.add_material(db, course, kind, title=title, unit_label=unit_label,
                                 filename=file.filename, data=_read_upload(file))
    else:
        m = service.add_material(db, course, kind, title=title, unit_label=unit_label, url=_check_url(url))
    audit_log(db, user.id, "courses", "material_added", "course_material", m.id,
              {"course_id": course.id, "kind": kind.value, "title": m.title})
    db.commit()
    return _material_out(m, set(), True)


@router.put("/{course_id}/materials/{material_id}/file")
def replace_material_file(course_id: int, material_id: int, db: DB, user: CurrentUser,
                          file: UploadFile = File(...)) -> dict:
    access.require_privilege(db, user, "courses.manage")
    course = service.visible_course(db, user, course_id)
    m = _material(db, course_id, material_id)
    service.replace_material_file(db, course, m, file.filename or "file", _read_upload(file))
    audit_log(db, user.id, "courses", "material_file_replaced", "course_material", m.id, {"course_id": course.id})
    db.commit()
    return _material_out(m, set(), True)


@router.delete("/{course_id}/materials/{material_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_material(course_id: int, material_id: int, db: DB, user: CurrentUser) -> None:
    access.require_privilege(db, user, "courses.manage")
    course = service.visible_course(db, user, course_id)
    m = _material(db, course_id, material_id)
    audit_log(db, user.id, "courses", "material_deleted", "course_material", m.id,
              {"course_id": course.id, "title": m.title})
    service.drop_file(db, course, m.path)
    course.materials.remove(m)
    db.commit()


class MaterialEdit(BaseModel):
    kind: MaterialKind | None = None
    external_url: str | None = None
    title: str | None = Field(None, min_length=1, max_length=300)
    unit: int | None = None
    unit_label: str | None = Field(None, max_length=100)
    sort_order: int | None = None
    is_released: bool | None = None


def _material(db: DB, course_id: int, material_id: int) -> CourseMaterial:
    m = db.get(CourseMaterial, material_id)
    if m is None or m.course_id != course_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Material not found")
    return m


@router.patch("/{course_id}/materials/{material_id}")
def edit_material(course_id: int, material_id: int, payload: MaterialEdit, db: DB, user: CurrentUser) -> dict:
    access.require_privilege(db, user, "courses.manage")
    service.visible_course(db, user, course_id)
    m = _material(db, course_id, material_id)
    changes = payload.model_dump(exclude_unset=True)
    for key, value in changes.items():
        if key in {"kind", "title"} and value is None:
            continue
        if key == "unit_label" and value == "":
            value = None
        if key == "external_url":
            if not m.external_url or value is None:
                continue  # only a link's address is editable
            value = _check_url(value)
        setattr(m, key, value)
    audit_log(db, user.id, "courses", "material_edited", "course_material", m.id,
              {"course_id": course_id, **{k: str(v) for k, v in changes.items()}})
    db.commit()
    return {"ok": True}


@router.put("/{course_id}/materials/{material_id}/progress", status_code=status.HTTP_204_NO_CONTENT)
def mark_done(course_id: int, material_id: int, db: DB, user: CurrentUser) -> None:
    service.visible_course(db, user, course_id)
    m = _material(db, course_id, material_id)
    if not m.is_released and not service.can_manage(db, user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This material hasn't been released yet")
    if db.get(CourseProgress, (user.id, m.id)) is None:
        db.add(CourseProgress(user_id=user.id, material_id=m.id))
        db.commit()


@router.delete("/{course_id}/materials/{material_id}/progress", status_code=status.HTTP_204_NO_CONTENT)
def unmark_done(course_id: int, material_id: int, db: DB, user: CurrentUser) -> None:
    service.visible_course(db, user, course_id)
    row = db.get(CourseProgress, (user.id, _material(db, course_id, material_id).id))
    if row is not None:
        db.delete(row)
        db.commit()


@router.get("/{course_id}/files/{path:path}")
def get_file(course_id: int, path: str, db: DB, user: CurrentUser) -> Response:
    """Serves the bundle verbatim, so its relative links (../assets/deck.css,
    ../book/week2.html) resolve inside this same prefix."""
    course = service.visible_course(db, user, course_id)
    if not service.can_manage(db, user):
        held = db.scalar(select(CourseMaterial.id).where(
            CourseMaterial.course_id == course.id, CourseMaterial.path == path,
            CourseMaterial.is_released.is_(False)))
        if held is not None:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "This material hasn't been released yet")
    row = db.scalar(select(CourseFile).where(CourseFile.course_id == course.id, CourseFile.path == path))
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")
    media = row.media_type
    if media.startswith("text/") or media in {"application/json", "image/svg+xml"}:
        media += "; charset=utf-8"
    return Response(row.content, media_type=media, headers={"Cache-Control": "private, no-cache"})
