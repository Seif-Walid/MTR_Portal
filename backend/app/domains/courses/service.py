"""Bundle import and the shelving rules.

A course is built either shelf by shelf — files uploaded straight onto a
shelf (kept under `_uploads/<shelf>/`) and links — or by importing a bundle.
A bundle is a plain folder of files (uploaded as a zip). Its viewable
documents — HTML pages and PDFs — are filed onto a shelf by the folder they sit
in (`slides/`, `book/`, `tasks/`, `solutions/`, …); any viewable document
outside those folders goes on the Tools shelf. Everything else (CSS, JS, JSON,
images) is stored and served but not listed. The automatic filing is only a
first guess: every material's shelf, title, unit and release state can be
edited afterwards, and re-uploading a bundle keeps those edits for files that
are still there."""

import html
import io
import mimetypes
import re
import zipfile
from pathlib import PurePosixPath
from urllib.parse import urlparse

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.domains.access import service as access
from app.domains.courses.models import (
    Course,
    CourseFile,
    CourseMaterial,
    CourseProgress,
    MaterialKind,
)
from app.domains.users.models import User

KIND_LABEL: dict[str, str] = {
    MaterialKind.SLIDES: "Slides",
    MaterialKind.BOOK: "Book",
    MaterialKind.TASKS: "Tasks",
    MaterialKind.ANSWERS: "Task answers",
    MaterialKind.TOOLS: "Tools",
}

# Top-level folder name -> shelf. Anything viewable elsewhere is a tool.
FOLDER_KIND: dict[str, str] = {
    **dict.fromkeys(("slides", "slide", "deck", "decks", "presentations"), MaterialKind.SLIDES),
    **dict.fromkeys(("book", "books", "chapters", "chapter", "handbook", "reading"), MaterialKind.BOOK),
    **dict.fromkeys(("tasks", "task", "exercises", "homework", "assignments"), MaterialKind.TASKS),
    **dict.fromkeys(("solutions", "solution", "answers", "answer"), MaterialKind.ANSWERS),
}
VIEWABLE = {".html", ".htm", ".pdf"}
# Authoring leftovers never uploaded: build scripts, caches, dotfiles, and
# the author's markdown notes (nothing in a bundle renders them).
SKIP_DIRS = {"build", "__pycache__", "node_modules"}
SKIP_SUFFIXES = (".pyc", ".md")
# The bundle's own landing page is served (pages link back to it) but the
# portal's course page replaces it, so it isn't shelved.
HOME_PAGES = {"index.html", "index.htm"}

COVER_DIR = "_cover"
UPLOAD_DIR = "_uploads"
# Files that belong to the course rather than to its bundle: a bundle
# re-upload never touches them.
OWN_PREFIXES = (f"{COVER_DIR}/", f"{UPLOAD_DIR}/")

MAX_BUNDLE_BYTES = 200 * 1024 * 1024
MAX_BUNDLE_FILES = 5000

_UNIT = re.compile(r"(week|chapter|session|lesson|unit|module)[\s_-]*(\d+)", re.I)
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
_SHELF_WORDS = r"(slides?|tasks?|solutions?|answers?|chapter)"


def _skipped(path: str) -> bool:
    parts = PurePosixPath(path).parts
    return any(p.startswith(".") or p in SKIP_DIRS for p in parts) or path.lower().endswith(SKIP_SUFFIXES)


def read_zip(data: bytes) -> dict[str, bytes]:
    """{bundle path: bytes}. A zip of a single folder is unwrapped, so zipping
    the course folder itself and zipping its contents both work."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The bundle must be a .zip file")
    infos = [i for i in zf.infolist() if not i.is_dir()]
    if len(infos) > MAX_BUNDLE_FILES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Bundle has over {MAX_BUNDLE_FILES} files")
    if sum(i.file_size for i in infos) > MAX_BUNDLE_BYTES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Bundle is too large once unpacked")
    names = [i.filename.replace("\\", "/") for i in infos]
    if any(n.startswith("/") or ".." in PurePosixPath(n).parts for n in names):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Bundle contains unsafe paths")
    names_kept = [n for n in names if not n.startswith("__MACOSX/")]
    tops = {PurePosixPath(n).parts[0] for n in names_kept}
    strip = len(tops) == 1 and all(len(PurePosixPath(n).parts) > 1 for n in names_kept)
    files: dict[str, bytes] = {}
    for info, name in zip(infos, names):
        if name.startswith("__MACOSX/"):
            continue
        path = "/".join(PurePosixPath(name).parts[1:]) if strip else name
        if path and not _skipped(path):
            files[path] = zf.read(info)
    if not files:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The bundle is empty")
    return files


def read_folder(root) -> dict[str, bytes]:
    """Same as read_zip, from a folder on disk (the import script)."""
    from pathlib import Path

    root = Path(root)
    files = {}
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root).as_posix()
        if p.is_file() and not _skipped(rel):
            files[rel] = p.read_bytes()
    return files


def media_type_of(path: str) -> str:
    if path.endswith(".js") or path.endswith(".mjs"):
        return "text/javascript"
    guessed, _ = mimetypes.guess_type(path)
    return guessed or "application/octet-stream"


def _kind_of(path: str) -> str | None:
    p = PurePosixPath(path)
    if p.suffix.lower() not in VIEWABLE or path.lower() in HOME_PAGES:
        return None
    if len(p.parts) > 1:
        return FOLDER_KIND.get(p.parts[0].lower(), MaterialKind.TOOLS)
    return MaterialKind.TOOLS


def _title_of(path: str, data: bytes) -> str:
    """The page's <title>, minus the site suffix ("— MTR Slides") and the
    unit/shelf prefix ("Week 2 Tasks ·") the course page shows on its own."""
    title = None
    if PurePosixPath(path).suffix.lower() in {".html", ".htm"}:
        m = _TITLE.search(data[:20000].decode("utf-8", "replace"))
        if m:
            title = html.unescape(" ".join(m.group(1).split()))
    if not title:
        return PurePosixPath(path).stem.replace("-", " ").replace("_", " ").strip().capitalize()
    title = re.split(r"\s+[—|]\s+", title)[0]
    title = re.sub(rf"^{_UNIT.pattern}\s*", "", title, flags=re.I)
    title = re.sub(rf"^{_SHELF_WORDS}\s*·\s*", "", title, flags=re.I)
    title = re.sub(r"^·\s*", "", title)
    return title.strip() or PurePosixPath(path).stem


def _unit_of(path: str) -> tuple[int | None, str | None]:
    m = _UNIT.search(PurePosixPath(path).name)
    if not m:
        return None, None
    return int(m.group(2)), f"{m.group(1).capitalize()} {int(m.group(2))}"


def shelve(files: dict[str, bytes]) -> list[dict]:
    """The automatic first filing of a bundle's viewable documents."""
    out = []
    for path in sorted(files):
        kind = _kind_of(path)
        if kind is None:
            continue
        unit, unit_label = _unit_of(path)
        out.append({
            "kind": kind,
            "path": path,
            "title": _title_of(path, files[path]),
            "unit": unit,
            "unit_label": unit_label,
            "is_released": kind != MaterialKind.ANSWERS,
        })
    out.sort(key=lambda m: (m["unit"] is None, m["unit"] or 0, m["path"]))
    for i, m in enumerate(out):
        m["sort_order"] = i
    return out


def replace_bundle(db: Session, course: Course, files: dict[str, bytes]) -> dict:
    """Swap the course's files for `files`. Materials whose file is still in
    the bundle keep their edits (and learners' progress); new documents are
    shelved automatically; materials whose file is gone are dropped."""
    # Cover images, files uploaded onto a shelf and links live beside the
    # bundle, not in it.
    bundle_ids = [fid for fid, path in db.execute(
        select(CourseFile.id, CourseFile.path).where(CourseFile.course_id == course.id))
        if not path.startswith(OWN_PREFIXES)]
    if bundle_ids:
        db.execute(delete(CourseFile).where(CourseFile.id.in_(bundle_ids)))
    files = {p: d for p, d in files.items() if not p.startswith(OWN_PREFIXES)}
    for path, data in files.items():
        db.add(CourseFile(course_id=course.id, path=path, media_type=media_type_of(path),
                          size=len(data), content=data))
    existing = {m.path: m for m in course.materials
                if m.path is not None and not m.path.startswith(OWN_PREFIXES)}
    added = removed = 0
    next_order = max((m.sort_order for m in existing.values()), default=-1) + 1
    for spec in shelve(files):
        if spec["path"] in existing:
            continue
        spec["sort_order"] += next_order
        course.materials.append(CourseMaterial(**spec))
        added += 1
    for path, material in existing.items():
        if path not in files:
            course.materials.remove(material)
            removed += 1
    if course.cover_path and course.cover_path not in files and not course.cover_path.startswith(OWN_PREFIXES):
        course.cover_path = None
    db.flush()
    return {"files": len(files), "materials_added": added, "materials_removed": removed}


def material_sort_key(m: CourseMaterial) -> tuple:
    """Shelf order: week 1 before week 7, whatever order the files were added
    in. Items with no unit sit after the numbered ones, in their own order."""
    return (m.unit is None, m.unit or 0, m.sort_order, m.id or 0)


def _next_order(course: Course) -> int:
    return max((m.sort_order for m in course.materials), default=-1) + 1


def _safe_name(filename: str) -> str:
    name = PurePosixPath((filename or "file").replace("\\", "/")).name
    name = re.sub(r"[^A-Za-z0-9._ -]+", "_", name).strip(" .") or "file"
    return name[:150]


def store_upload(db: Session, course: Course, kind: str, filename: str, data: bytes) -> str:
    """Saves an uploaded file under the shelf's upload folder; never
    overwrites — a clashing name gets a -2, -3, … suffix."""
    name = _safe_name(filename)
    stem, suffix = PurePosixPath(name).stem, PurePosixPath(name).suffix
    taken = set(db.scalars(select(CourseFile.path).where(
        CourseFile.course_id == course.id, CourseFile.path.like(f"{UPLOAD_DIR}/{kind}/%"))))
    path, n = f"{UPLOAD_DIR}/{kind}/{name}", 2
    while path in taken:
        path, n = f"{UPLOAD_DIR}/{kind}/{stem}-{n}{suffix}", n + 1
    db.add(CourseFile(course_id=course.id, path=path, media_type=media_type_of(path), size=len(data), content=data))
    return path


def add_material(
    db: Session, course: Course, kind: str, *, title: str | None, unit_label: str | None,
    filename: str | None = None, data: bytes | None = None, url: str | None = None,
) -> CourseMaterial:
    """Puts one file or one link onto a shelf. Title and unit default to what
    the file says about itself (its <title>, a "week3" in its name)."""
    if data is not None:
        path = store_upload(db, course, kind, filename or "file", data)
        auto_title = _title_of(path, data)
        unit, auto_label = _unit_of(filename or path)
    else:
        host = urlparse(url or "").hostname or url
        path, auto_title, unit, auto_label = None, re.sub(r"^www\.", "", host or ""), None, None
    if unit_label:
        m = re.search(r"\d+", unit_label)
        unit = int(m.group()) if m else None
    material = CourseMaterial(
        kind=kind, title=(title or "").strip() or auto_title or "Untitled",
        path=path, external_url=url, unit=unit, unit_label=unit_label or auto_label,
        sort_order=_next_order(course), is_released=kind != MaterialKind.ANSWERS,
    )
    course.materials.append(material)
    db.flush()
    return material


def replace_material_file(db: Session, course: Course, material: CourseMaterial, filename: str, data: bytes) -> None:
    """New content for a material. A file uploaded onto the shelf is swapped
    in place; a bundle page or a link becomes an uploaded file."""
    if material.path and material.path.startswith(f"{UPLOAD_DIR}/"):
        drop_file(db, course, material.path)
    material.path = store_upload(db, course, material.kind, filename, data)
    material.external_url = None
    db.flush()


def drop_file(db: Session, course: Course, path: str | None) -> None:
    """Removes a shelf upload's file. Bundle files stay: other pages of the
    bundle may link to them."""
    if path and path.startswith(f"{UPLOAD_DIR}/"):
        db.execute(delete(CourseFile).where(CourseFile.course_id == course.id, CourseFile.path == path))


# --- access ------------------------------------------------------------------

def can_manage(db: Session, user: User) -> bool:
    return access.has_privilege(db, user, "courses.manage")


def visible_course(db: Session, user: User, course_id: int) -> Course:
    access.require_privilege(db, user, "courses.view")
    course = db.get(Course, course_id)
    if course is None or (not course.is_published and not can_manage(db, user)):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Course not found")
    return course


def completed_ids(db: Session, user: User, course_id: int) -> set[int]:
    return set(db.scalars(
        select(CourseProgress.material_id)
        .join(CourseMaterial, CourseMaterial.id == CourseProgress.material_id)
        .where(CourseProgress.user_id == user.id, CourseMaterial.course_id == course_id)
    ))


def file_count(db: Session, course_id: int) -> int:
    return db.scalar(select(func.count()).select_from(CourseFile).where(CourseFile.course_id == course_id)) or 0
