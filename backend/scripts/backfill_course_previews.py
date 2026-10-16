"""Build cached PDF renditions for office-file course materials uploaded before
previews existed, so they show inline in the viewer instead of only downloading.

Safe to re-run: only materials still missing a rendition are touched. Needs
LibreOffice on the machine (the backend image ships it).

Usage (from backend/, with the venv):
    DATABASE_URL=sqlite:///./portal_dev.db .venv/bin/python -m scripts.backfill_course_previews
"""

from app.core.database import SessionLocal
from app.domains.courses import preview, service


def main() -> None:
    if not preview.available():
        raise SystemExit("LibreOffice (soffice) not found — install it or run inside the backend image.")
    db = SessionLocal()
    try:
        result = service.backfill_previews(db)
    finally:
        db.close()
    print(f"Renditions built: {result['made']}, failed: {result['failed']}")


if __name__ == "__main__":
    main()
