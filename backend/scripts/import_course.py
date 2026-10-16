"""Load a course folder into the portal as a course — the same import the
Courses page runs on an uploaded zip, straight from disk.

Re-running against an existing course (--course-id) replaces its bundle and
keeps every material edit (shelf, title, release state) for files that are
still there.

Usage (from backend/, with the venv):
    DATABASE_URL=sqlite:///./portal_dev.db \\
        .venv/bin/python -m scripts.import_course ../../MTR_Lessons \\
        --title "ROV Software (Python)" --label "PY"
    # add --commit to write; without it, does a dry run and prints the shelves.
"""

import argparse
from pathlib import Path

from app.core.database import SessionLocal
from app.domains.courses import service
from app.domains.courses.models import Course


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", type=Path)
    ap.add_argument("--title")
    ap.add_argument("--description")
    ap.add_argument("--label", help="short text set large on the cover")
    ap.add_argument("--accent", default="#5cc6ff")
    ap.add_argument("--course-id", type=int, help="replace this course's bundle instead")
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()

    files = service.read_folder(args.folder)
    shelves = service.shelve(files)
    print(f"{len(files)} files, {len(shelves)} materials")
    for m in shelves:
        held = "" if m["is_released"] else "  [held back]"
        print(f"  {m['kind']:8} {m['unit_label'] or '-':8} {m['title']}  ({m['path']}){held}")

    db = SessionLocal()
    try:
        if args.course_id:
            course = db.get(Course, args.course_id)
            if course is None:
                raise SystemExit(f"No course {args.course_id}")
        else:
            if not args.title:
                raise SystemExit("--title is required for a new course")
            course = Course(title=args.title, description=args.description,
                            cover_label=args.label, accent=args.accent)
            db.add(course)
            db.flush()
        print(service.replace_bundle(db, course, files))
        if args.commit:
            db.commit()
            print(f"Committed course {course.id}")
        else:
            db.rollback()
            print("Dry run — add --commit to write")
    finally:
        db.close()


if __name__ == "__main__":
    main()
