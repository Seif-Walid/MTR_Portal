"""Courses: the catalogue, the course page's shelves, the bundle's files, and
handing task sheets out as Tasks. Viewing is gated by courses.view; uploading
bundles, editing the shelves and handing out tasks by courses.manage. A
learner's progress is the share of the course's task sheets they have
submitted through the Tasks tab. Held-back materials (task answers until
they're released) are refused to learners at the file level, not just hidden
from the list."""

from datetime import date
from urllib.parse import quote
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.config import settings
from app.domains.access import service as access
from app.domains.audit.service import log as audit_log
from app.domains.auth.deps import DB, CurrentUser
from app.domains.courses import preview, service
from app.domains.courses.models import Course, CourseFile, CourseMaterial, MaterialKind
from app.domains.notifications.models import NotificationType
from app.domains.notifications.service import notify
from app.domains.tasks.models import Task
from app.domains.users.models import User

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


def _course_out(course: Course, submitted: set[int]) -> dict:
    counts = {k.value: 0 for k in MaterialKind}
    for m in course.materials:
        counts[m.kind] = counts.get(m.kind, 0) + 1
    sheets = [m for m in course.materials if m.kind == MaterialKind.TASKS]
    total = len(sheets)
    completed = sum(1 for m in sheets if m.id in submitted)
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
        # progress: task sheets submitted as Tasks out of all the course's sheets
        "total": total,
        "completed": completed,
        "percent": round(100 * completed / total) if total else 0,
        "updated_at": course.updated_at,
    }


def _material_out(m: CourseMaterial, mine: dict[int, Task], manage: bool,
                  stats: dict[int, dict]) -> dict:
    open_ = m.is_released or manage
    if m.external_url:
        url = m.external_url
    else:
        url = _file_url(m.course_id, m.path) if m.path else None
    task = mine.get(m.id)
    return {
        "id": m.id,
        "kind": m.kind,
        "title": m.title,
        "path": m.path if manage else None,
        "is_link": bool(m.external_url),
        "media_type": service.media_type_of(m.path) if m.path else None,
        # A cached PDF rendition of an office file, shown inline in the viewer.
        "preview_url": _file_url(m.course_id, m.preview_path) if (m.preview_path and open_) else None,
        "unit": m.unit,
        "unit_label": m.unit_label,
        "sort_order": m.sort_order,
        "is_released": m.is_released,
        "url": url if open_ else None,
        "completed": task is not None and task.status in service.DONE_STATUSES,
        # the viewer's own Task for this sheet, if it was handed to them
        "task": {"id": task.id, "status": task.status} if task is not None else None,
        # managers: how many it went to / how many submitted
        "handout": stats.get(m.id) if manage and m.kind == MaterialKind.TASKS else None,
    }


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
    done = service.submitted_ids(service.my_course_tasks(db, user))
    return [_course_out(c, done) for c in db.scalars(q)]


@router.get("/{course_id}")
def get_course(course_id: int, db: DB, user: CurrentUser) -> dict:
    course = service.visible_course(db, user, course_id)
    manage = service.can_manage(db, user)
    mine = service.my_course_tasks(db, user, course.id)
    stats = service.task_sheet_stats(db, course.id) if manage else {}
    mats = sorted(course.materials, key=service.material_sort_key)
    out = _course_out(course, service.submitted_ids(mine))
    out["materials"] = [_material_out(m, mine, manage, stats) for m in mats]
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
    return _material_out(m, {}, True, {})


@router.put("/{course_id}/materials/{material_id}/file")
def replace_material_file(course_id: int, material_id: int, db: DB, user: CurrentUser,
                          file: UploadFile = File(...)) -> dict:
    access.require_privilege(db, user, "courses.manage")
    course = service.visible_course(db, user, course_id)
    m = _material(db, course_id, material_id)
    service.replace_material_file(db, course, m, file.filename or "file", _read_upload(file))
    audit_log(db, user.id, "courses", "material_file_replaced", "course_material", m.id, {"course_id": course.id})
    db.commit()
    return _material_out(m, {}, True, {})


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


@router.get("/{course_id}/learners")
def learners(course_id: int, db: DB, user: CurrentUser) -> dict:
    """Who task sheets can be handed to: everyone who can view courses, and
    the live event teams (a team hands out to all its people at once)."""
    access.require_privilege(db, user, "courses.manage")
    service.visible_course(db, user, course_id)
    from app.domains.events.models import EventTeam
    from app.domains.tasks.service import archived_team_ids

    ids = access.users_with_privilege(db, "courses.view") - {user.id}
    people = db.scalars(select(User).where(User.id.in_(ids)).order_by(User.full_name))
    dead = archived_team_ids(db)
    teams = [t for t in db.scalars(select(EventTeam)) if t.id not in dead]
    return {
        "people": [{"id": u.id, "full_name": u.full_name} for u in people],
        "teams": sorted(({"id": t.id, "name": t.path_name} for t in teams), key=lambda t: t["name"]),
    }


class HandOut(BaseModel):
    """Hand task sheets out as Tasks: a whole unit ("week 2") or picked
    sheets, to picked people and/or everyone on an event team."""
    unit: int | None = None
    material_ids: list[int] = Field(default_factory=list)
    assignee_ids: list[int] = Field(default_factory=list)
    event_team_id: int | None = None
    due_date: date | None = None


@router.post("/{course_id}/hand-out")
def hand_out(course_id: int, payload: HandOut, db: DB, user: CurrentUser) -> dict:
    """Releases the chosen task sheets and gives each learner one Task per
    sheet (assigned by the instructor, so the instructor reviews it). The
    Task is the only thing that moves progress: submitting it from the Tasks
    tab. Someone who already has a Task for a sheet isn't given a second."""
    access.require_privilege(db, user, "courses.manage")
    course = service.visible_course(db, user, course_id)
    sheets = [m for m in course.materials if m.kind == MaterialKind.TASKS and (
        m.id in payload.material_ids
        or (payload.unit is not None and m.unit == payload.unit))]
    if not sheets:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No task sheets match")

    learner_ids = set(payload.assignee_ids)
    if payload.event_team_id is not None:
        from app.domains.events.models import EventTeam
        from app.domains.events.service import team_member_user_ids
        if db.get(EventTeam, payload.event_team_id) is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Team not found")
        learner_ids |= team_member_user_ids(db, payload.event_team_id)
    learner_ids.discard(user.id)
    learners = [u for u in (db.get(User, uid) for uid in sorted(learner_ids))
                if u is not None and u.is_active and access.has_privilege(db, u, "courses.view")]
    if not learners:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Nobody to hand this to")

    have = set(db.execute(
        select(Task.course_material_id, Task.assignee_id).where(
            Task.course_material_id.in_([m.id for m in sheets]))).tuples())
    created = skipped = 0
    for m in sorted(sheets, key=service.material_sort_key):
        m.is_released = True
        batch = uuid4().hex if len(learners) > 1 else None
        for learner in learners:
            if (m.id, learner.id) in have:
                skipped += 1
                continue
            when = f"{m.unit_label} · " if m.unit_label else ""
            task = Task(
                title=f"{course.title} · {when}{m.title}"[:255],
                description=f"Course task sheet — open it from Courses → {course.title}.",
                assigner_id=user.id, assignee_id=learner.id, due_date=payload.due_date,
                category="Course", course_material_id=m.id, batch_id=batch,
                event_team_id=payload.event_team_id,
            )
            db.add(task)
            db.flush()
            notify(db, learner.id, NotificationType.TASK_ASSIGNED,
                   f"{user.full_name} assigned you a task: '{task.title}'", task_id=task.id)
            created += 1
    audit_log(db, user.id, "courses", "tasks_handed_out", "course", course.id,
              {"materials": [m.id for m in sheets], "learners": len(learners),
               "created": created, "skipped": skipped})
    db.commit()
    return {"created": created, "skipped": skipped, "learners": len(learners)}


@router.get("/{course_id}/files/{path:path}")
def get_file(course_id: int, path: str, db: DB, user: CurrentUser) -> Response:
    """Serves the bundle verbatim, so its relative links (../assets/deck.css,
    ../book/week2.html) resolve inside this same prefix."""
    course = service.visible_course(db, user, course_id)
    if not service.can_manage(db, user):
        # A rendition is gated by the file it renders, not by its own path.
        gate = preview.source_of(path) or path
        held = db.scalar(select(CourseMaterial.id).where(
            CourseMaterial.course_id == course.id, CourseMaterial.path == gate,
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
