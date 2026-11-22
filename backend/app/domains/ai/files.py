"""Documents the assistant makes: PDF or Excel, from one general builder.

The model describes the document as blocks instead of typing data into it:
- text:      markdown; {{column}} fills in values from the enclosing for_each row
- table:     a SQL query whose result is rendered as a table (a sheet in Excel)
- for_each:  a SQL query; its blocks repeat once per row (new page each by
             default), with that row's columns available to {{…}} and to the
             nested queries as :column parameters
- page_break
Every value comes from the database through the same permission-filtered,
read-only query layer the assistant uses to answer questions (data.py), so
nothing is miscopied, and any layout the user asks for is a matter of blocks
and SQL — no new tool per request.

Files are stored as AiFile rows, downloadable only by the person who made them.
"""

from __future__ import annotations

import io
import re
import sqlite3
from pathlib import Path

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.domains.ai import data
from app.domains.ai.models import AiFile
from app.domains.users.models import User

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PDF = "application/pdf"
MAX_BYTES = 20 * 1024 * 1024
MAX_ROWS = 20_000  # per table block
MAX_REPEAT = 500  # for_each iterations
NAVY, GREY, LIGHT = (31, 78, 120), (95, 105, 120), (234, 240, 248)


def _safe_name(name: str, ext: str) -> str:
    stem = re.sub(r"[^\w\- .()&]+", "", name.strip()).strip(" .")[:120] or "document"
    stem = re.sub(rf"\.{ext}$", "", stem, flags=re.I)
    return f"{stem}.{ext}"


def store(db: Session, user: User, conversation_id: int | None, filename: str, media_type: str, content: bytes) -> dict:
    if len(content) > MAX_BYTES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "File too large (over 20 MB); narrow the queries")
    rec = AiFile(user_id=user.id, conversation_id=conversation_id, filename=filename,
                 media_type=media_type, size=len(content), data=content)
    db.add(rec)
    db.commit()
    return {"file_id": rec.id, "filename": filename, "size": len(content),
            "download": f"/api/ai/files/{rec.id}",
            "note": "The file appears to the user as a download link in the portal chat."}


# ------------------------------------------------------------------ blocks
def _sqls(blocks: list[dict]) -> list[str]:
    out = []
    for b in blocks:
        for key in ("table", "for_each"):
            if b.get(key):
                out.append(b[key])
        out += _sqls(b.get("blocks") or [])
    return out


_PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")


def _fill(text: str, ctx: dict) -> str:
    def sub(m):
        v = ctx.get(m.group(1))
        return "" if v is None else str(v)
    return _PLACEHOLDER.sub(sub, text)


def _select(conn: sqlite3.Connection, sql: str, ctx: dict, limit: int) -> dict:
    return data.run(conn, sql, params=ctx, limit=limit)


class _Walker:
    """Runs the block tree once, handing each piece to a renderer."""

    def __init__(self, conn: sqlite3.Connection, renderer) -> None:
        self.conn, self.r = conn, renderer
        self.stats = {"tables": 0, "rows": 0, "repeats": 0}

    def walk(self, blocks: list[dict], ctx: dict) -> None:
        for b in blocks:
            if b.get("page_break"):
                self.r.page_break()
            elif b.get("text") is not None:
                self.r.text(_fill(b["text"], ctx))
            elif b.get("table"):
                res = _select(self.conn, b["table"], ctx, MAX_ROWS)
                self.stats["tables"] += 1
                self.stats["rows"] += len(res["rows"])
                self.r.table(_fill(b.get("heading") or "", ctx), res["columns"], res["rows"], ctx,
                             b.get("empty") or "None.")
            elif b.get("for_each"):
                res = _select(self.conn, b["for_each"], ctx, MAX_REPEAT)
                for i, row in enumerate(res["rows"]):
                    self.stats["repeats"] += 1
                    if b.get("new_page", True) and (i or not self.r.page_is_fresh()):
                        self.r.page_break()
                    self.walk(b.get("blocks") or [], {**ctx, **dict(zip(res["columns"], row))})


# --------------------------------------------------------------------- pdf
_FONT_DIRS = ["/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/dejavu", "/usr/share/fonts/TTF"]
_NO_GLYPH = re.compile("[\U00010000-\U0010FFFF☀-➿️‍]")


def _font(pdf) -> str:
    for d in _FONT_DIRS:
        regular, bold = Path(d, "DejaVuSans.ttf"), Path(d, "DejaVuSans-Bold.ttf")
        if regular.exists():
            pdf.add_font("DejaVu", "", str(regular))
            pdf.add_font("DejaVu", "B", str(bold if bold.exists() else regular))
            pdf.add_font("DejaVu", "I", str(regular))
            pdf.add_font("DejaVu", "BI", str(bold if bold.exists() else regular))
            return "DejaVu"
    return ""  # core font: latin-1 only


class _Pdf:
    def __init__(self, title: str) -> None:
        import markdown
        from fpdf import FPDF
        from fpdf.fonts import FontFace

        self.md, self.FontFace = markdown, FontFace
        self.doc = FPDF(format="A4")
        self.doc.set_auto_page_break(True, margin=14)
        self.doc.set_title(title)
        self.family = _font(self.doc) or "helvetica"
        if self.family != "helvetica":
            try:
                self.doc.set_text_shaping(True)  # Arabic joining + right-to-left (uharfbuzz)
            except Exception:  # noqa: BLE001
                pass
        self.styles = {
            "h1": FontFace(color=NAVY, emphasis="BOLD", size_pt=18),
            "h2": FontFace(color=NAVY, emphasis="BOLD", size_pt=14),
            "h3": FontFace(color=(40, 40, 40), emphasis="BOLD", size_pt=12),
            "h4": FontFace(color=(40, 40, 40), emphasis="BOLD", size_pt=10.5),
        }
        self.doc.add_page()
        self._fresh = True

    def s(self, text: str) -> str:
        if self.family == "helvetica":
            return text.encode("latin-1", "replace").decode("latin-1")
        return _NO_GLYPH.sub("", text)  # emoji have no glyph: drop instead of boxes

    def page_is_fresh(self) -> bool:
        return self._fresh

    def page_break(self) -> None:
        if not self._fresh:
            self.doc.add_page()
            self._fresh = True

    def text(self, markdown_text: str) -> None:
        html = self.md.markdown(self.s(markdown_text), extensions=["tables", "sane_lists"])
        if not html.strip():
            return
        html = html.replace("<table>", '<table border="1" width="100%">')
        self.doc.set_font(self.family, "", 10)
        self.doc.set_text_color(0, 0, 0)
        self.doc.write_html(html, font_family=self.family, table_line_separators=True, tag_styles=self.styles)
        self._fresh = False

    def table(self, heading: str, columns: list[str], rows: list[list], ctx: dict, empty: str) -> None:
        doc = self.doc
        if heading:
            if doc.get_y() > doc.h - 40:
                self.page_break()
            doc.ln(1)
            doc.set_font(self.family, "B", 11.5)
            doc.set_text_color(*NAVY)
            doc.multi_cell(0, 6.5, self.s(heading), new_x="LMARGIN", new_y="NEXT")
        doc.set_text_color(0, 0, 0)
        doc.set_font(self.family, "", 9.5)
        if not rows:
            doc.set_text_color(*GREY)
            doc.multi_cell(0, 5.5, self.s(empty), new_x="LMARGIN", new_y="NEXT")
            doc.set_text_color(0, 0, 0)
        else:
            with doc.table(line_height=5.6, first_row_as_headings=True, text_align="LEFT",
                           headings_style=self.FontFace(emphasis="BOLD", color=NAVY, fill_color=LIGHT),
                           borders_layout="HORIZONTAL_LINES") as t:
                t.row([self.s(c.replace("_", " ").strip().capitalize()) for c in columns])
                for r in rows:
                    t.row(["" if v is None else self.s(str(v)) for v in r])
        doc.ln(2)
        self._fresh = False

    def output(self) -> bytes:
        return bytes(self.doc.output())


# -------------------------------------------------------------------- xlsx
def _excel_value(v):
    if v is None or isinstance(v, (int, float, bool)):
        return v
    s = str(v)
    if s.startswith(("=", "+", "-", "@")) and not re.fullmatch(r"-?\d+(\.\d+)?", s):
        return "'" + s  # never let text become a formula
    return s


class _Xlsx:
    """Each table block becomes a sheet; text blocks collect on a Notes sheet."""

    def __init__(self, title: str) -> None:
        self.sheets: list[tuple[str, list[str], list[list]]] = []
        self.notes: list[str] = []
        self.title = title

    def page_is_fresh(self) -> bool:
        return True

    def page_break(self) -> None:
        pass

    def text(self, markdown_text: str) -> None:
        if markdown_text.strip():
            self.notes.append(markdown_text.strip())

    def table(self, heading: str, columns: list[str], rows: list[list], ctx: dict, empty: str) -> None:
        label = heading or next((str(v) for v in ctx.values() if isinstance(v, str) and v), "") or f"Sheet {len(self.sheets) + 1}"
        self.sheets.append((label, columns, rows))

    def output(self) -> bytes:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill
        from openpyxl.utils import get_column_letter

        wb = Workbook()
        wb.remove(wb.active)
        used: set[str] = set()
        sheets = list(self.sheets)
        if self.notes:
            sheets.insert(0, ("Notes", [self.title], [[n] for n in self.notes]))
        for title, header, rows in sheets or [("Empty", [], [])]:
            name = re.sub(r"[\[\]:*?/\\]", " ", title).strip()[:31] or "Sheet"
            base, n = name, 2
            while name.lower() in used:
                name = f"{base[:27]} ({n})"
                n += 1
            used.add(name.lower())
            ws = wb.create_sheet(name)
            ws.append(list(header))
            for cell in ws[1]:
                cell.font = Font(bold=True, color="FFFFFF")
                cell.fill = PatternFill("solid", fgColor="1F4E78")
            for row in rows:
                ws.append([_excel_value(v) for v in row])
            ws.freeze_panes = "A2"
            for i, h in enumerate(header, start=1):
                width = max([len(str(h))] + [len(str(r[i - 1])) for r in rows[:200] if r[i - 1] is not None])
                ws.column_dimensions[get_column_letter(i)].width = min(max(width + 2, 8), 60)
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()


# ------------------------------------------------------------------- entry
def make_document(db: Session, user: User, conversation_id: int | None, *, fmt: str, filename: str,
                  title: str, blocks: list[dict]) -> dict:
    conn = data.connect(db, user, _sqls(blocks))
    try:
        renderer = _Pdf(title) if fmt == "pdf" else _Xlsx(title)
        walker = _Walker(conn, renderer)
        walker.walk(blocks, {})
        content = renderer.output()
    finally:
        conn.close()
    ext, media = ("pdf", PDF) if fmt == "pdf" else ("xlsx", XLSX)
    out = store(db, user, conversation_id, _safe_name(filename, ext), media, content)
    out["built"] = walker.stats
    return out
