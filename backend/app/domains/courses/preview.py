"""PDF renditions of office documents, so slides and docs show inline in the
viewer instead of only downloading.

Office formats (.pptx, .docx, .xlsx, …) can't be shown in a browser frame, and
the portal's files are private, so the public Office/Google viewers can't reach
them either. The one reliable answer is to render a PDF with LibreOffice.

That is done once, when the file is uploaded (and by a one-off backfill for
files already stored), never while a learner is viewing: the conversion's brief
memory spike stays off the serving path, and every view just streams the cached
PDF. Conversions are serialized so at most one LibreOffice runs at a time, which
keeps the peak bounded on a small VM. If LibreOffice is missing or a conversion
fails, the rendition is simply skipped and the file falls back to a download."""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path, PurePosixPath
from threading import Lock

log = logging.getLogger(__name__)

# Office formats LibreOffice renders well to PDF. PDFs are already inline and
# images/html need no rendition, so they're not here.
CONVERTIBLE = {
    ".ppt", ".pptx", ".odp",
    ".doc", ".docx", ".odt", ".rtf",
    ".xls", ".xlsx", ".ods", ".csv",
}

# Where a rendition is stored, relative to the course: the source path with
# this prefix and a .pdf suffix. Kept out of OWN_PREFIXES so a bundle re-upload
# can rebuild it.
PREVIEW_DIR = "_previews"

_SOFFICE = shutil.which("soffice") or shutil.which("libreoffice")
_lock = Lock()  # one LibreOffice at a time: bounds peak memory on a small VM.
_TIMEOUT = 180  # seconds; a slow conversion is abandoned rather than hung.


def can_preview(path: str) -> bool:
    """True when `path` names a file LibreOffice can render to PDF."""
    return PurePosixPath(path).suffix.lower() in CONVERTIBLE


def preview_path(source_path: str) -> str:
    """The stored path of `source_path`'s PDF rendition."""
    return f"{PREVIEW_DIR}/{source_path}.pdf"


def source_of(rendition_path: str) -> str | None:
    """The source path a `_previews/….pdf` rendition belongs to, or None."""
    if rendition_path.startswith(f"{PREVIEW_DIR}/") and rendition_path.endswith(".pdf"):
        return rendition_path[len(PREVIEW_DIR) + 1 : -len(".pdf")]
    return None


def available() -> bool:
    return _SOFFICE is not None


def to_pdf(data: bytes, filename: str) -> bytes | None:
    """Render `data` (an office file named `filename`) to PDF bytes, or None if
    LibreOffice is unavailable or the conversion fails. Never raises."""
    if _SOFFICE is None or not can_preview(filename):
        return None
    name = PurePosixPath(filename.replace("\\", "/")).name or "file"
    try:
        with _lock, tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            src = tmpdir / name
            src.write_bytes(data)
            profile = tmpdir / "profile"
            proc = subprocess.run(
                [
                    _SOFFICE, "--headless", "--nologo", "--nofirststartwizard",
                    f"-env:UserInstallation=file://{profile}",
                    "--convert-to", "pdf", "--outdir", str(tmpdir), str(src),
                ],
                capture_output=True, timeout=_TIMEOUT, check=False,
            )
            out = src.with_suffix(".pdf")
            if out.exists() and out.stat().st_size > 0:
                return out.read_bytes()
            log.warning("preview: LibreOffice made no PDF for %s (rc=%s): %s",
                        name, proc.returncode, proc.stderr[:500].decode("utf-8", "replace"))
    except subprocess.TimeoutExpired:
        log.warning("preview: LibreOffice timed out on %s", name)
    except Exception:  # noqa: BLE001 — a preview is best-effort; uploads must not fail on it.
        log.exception("preview: conversion failed for %s", name)
    return None
