"""Courses: bundle upload and automatic shelving, the gated file server (held
back answers refused to learners), progress from handed-out tasks, and re-upload keeping edits."""

import io
import zipfile

import pytest

from app.domains.access.models import AccessLevel


def _zip(files: dict[str, str], folder: str | None = "MTR_Lessons") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for path, text in files.items():
            zf.writestr(f"{folder}/{path}" if folder else path, text)
    return buf.getvalue()


BUNDLE = {
    "index.html": "<title>Hub</title>",
    "assets/mtr.css": "body{}",
    "slides/week1.html": "<title>Week 1 · Python Fundamentals — MTR Slides</title>",
    "book/week1.html": "<title>Chapter 1 · Python Fundamentals — MTR Software Handbook</title>",
    "tasks/week1.html": "<title>Week 1 Tasks · Python Fundamentals — MTR</title>",
    "solutions/week1.html": "<title>Week 1 Solutions · Python Fundamentals — MTR</title>",
    "reference/week6.html": "<title>Week 6 Reference · Linux &amp; Git — MTR</title>",
    "week2-functions-scope.html": "<title>Week 2 · Functions — MTR</title>",
    "build/gen.py": "print()",
    "NOTES.md": "# private",
    ".gitignore": "*.pyc",
}


@pytest.fixture()
def grant(db_session):
    """Learners (Member level) view courses; the admin manages them."""
    def _grant(level: str, *keys: str):
        import json
        lvl = db_session.query(AccessLevel).filter_by(name=level).one()
        lvl.privileges = json.dumps(sorted(lvl.privilege_keys | set(keys)))
        db_session.commit()
    return _grant


@pytest.fixture()
def course(login, grant):
    grant("Member", "courses.view")
    r = login("admin").post(
        "/api/courses",
        data={"title": "ROV Software (Python)", "cover_label": "PY"},
        files={"bundle": ("lessons.zip", _zip(BUNDLE), "application/zip")},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _materials(client, course_id):
    return {m["title"] + "|" + m["kind"]: m for m in client.get(f"/api/courses/{course_id}").json()["materials"]}


def test_upload_shelves_by_folder(login, course):
    detail = login("admin").get(f"/api/courses/{course}").json()
    kinds = {m["path"]: (m["kind"], m["title"], m["unit_label"], m["is_released"]) for m in detail["materials"]}
    assert kinds == {
        "slides/week1.html": ("slides", "Python Fundamentals", "Week 1", True),
        "book/week1.html": ("book", "Python Fundamentals", "Week 1", True),
        "tasks/week1.html": ("tasks", "Python Fundamentals", "Week 1", False),
        "solutions/week1.html": ("answers", "Python Fundamentals", "Week 1", False),
        "reference/week6.html": ("tools", "Reference · Linux & Git", "Week 6", True),
        "week2-functions-scope.html": ("tools", "Functions", "Week 2", True),
    }
    # the single top folder is unwrapped; authoring leftovers never stored
    assert detail["file_count"] == 8
    r = login("admin").get(f"/api/courses/{course}/files/build/gen.py")
    assert r.status_code == 404


def test_files_serve_with_relative_assets(login, course):
    member = login("comp_member")
    r = member.get(f"/api/courses/{course}/files/slides/week1.html")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert member.get(f"/api/courses/{course}/files/assets/mtr.css").headers["content-type"].startswith("text/css")


def test_held_back_answers_refused_to_learners(login, course):
    member = login("comp_member")
    mats = _materials(member, course)
    answers = mats["Python Fundamentals|answers"]
    assert answers["url"] is None and answers["path"] is None
    assert member.get(f"/api/courses/{course}/files/solutions/week1.html").status_code == 403
    assert login("admin").get(f"/api/courses/{course}/files/solutions/week1.html").status_code == 200

    r = login("admin").patch(f"/api/courses/{course}/materials/{answers['id']}", json={"is_released": True})
    assert r.status_code == 200
    assert member.get(f"/api/courses/{course}/files/solutions/week1.html").status_code == 200


def test_privileges(login, course):
    # Guest-level accounts see nothing; learners can't manage
    assert login("student").get("/api/courses").status_code == 403
    member = login("comp_member")
    assert member.patch(f"/api/courses/{course}", json={"title": "x"}).status_code == 403
    assert member.post("/api/courses", data={"title": "x"},
                       files={"bundle": ("b.zip", _zip(BUNDLE), "application/zip")}).status_code == 403


def test_unpublished_hidden_from_learners(login, course):
    login("admin").patch(f"/api/courses/{course}", json={"is_published": False})
    member = login("comp_member")
    assert member.get("/api/courses").json() == []
    assert member.get(f"/api/courses/{course}").status_code == 404
    assert member.get(f"/api/courses/{course}/files/assets/mtr.css").status_code == 404


def test_progress_counts_submitted_course_tasks(login, course, org):
    """Progress is task sheets submitted through the Tasks tab — opening
    slides or chapters moves nothing. The instructor hands out week 1."""
    admin, member = login("admin"), login("comp_member")
    sheet = _materials(admin, course)["Python Fundamentals|tasks"]
    assert sheet["is_released"] is False  # held back until handed out
    row = member.get("/api/courses").json()[0]
    assert (row["completed"], row["total"], row["percent"]) == (0, 1, 0)

    # learners can't hand tasks out
    assert member.post(f"/api/courses/{course}/hand-out",
                       json={"unit": 1, "assignee_ids": [org["comp_member"].id]}).status_code == 403
    picker = admin.get(f"/api/courses/{course}/learners").json()
    assert org["comp_member"].id in {p["id"] for p in picker["people"]}
    r = admin.post(f"/api/courses/{course}/hand-out",
                   json={"unit": 1, "assignee_ids": [org["comp_member"].id]})
    assert r.status_code == 200, r.text
    assert r.json()["created"] == 1
    # handing out again doesn't duplicate
    again = admin.post(f"/api/courses/{course}/hand-out",
                       json={"unit": 1, "assignee_ids": [org["comp_member"].id]})
    assert again.json() == {"created": 0, "skipped": 1, "learners": 1}

    mine = _materials(member, course)["Python Fundamentals|tasks"]
    assert mine["is_released"] is True and mine["task"]["status"] == "todo"
    task = next(t for t in member.get("/api/tasks").json() if t["course_material_id"] == sheet["id"])
    assert task["course_id"] == course and task["assigner"]["id"] == org["admin"].id
    assert member.get("/api/courses").json()[0]["completed"] == 0  # not yet submitted

    for st in ("in_progress", "submitted"):
        assert member.patch(f"/api/tasks/{task["id"]}/status", json={"status": st}).status_code == 200
    row = member.get("/api/courses").json()[0]
    assert (row["completed"], row["total"], row["percent"]) == (1, 1, 100)
    stats = _materials(admin, course)["Python Fundamentals|tasks"]["handout"]
    assert stats == {"assigned": 1, "submitted": 1}

    # sent back for revision, it no longer counts
    admin.patch(f"/api/tasks/{task["id"]}/status", json={"status": "revision_requested"})
    assert member.get("/api/courses").json()[0]["completed"] == 0


def test_reupload_keeps_edits(login, course):
    admin, member = login("admin"), login("comp_member")
    mats = _materials(admin, course)
    tool = mats["Functions|tools"]
    admin.patch(f"/api/courses/{course}/materials/{tool['id']}", json={"title": "Step-through", "kind": "book"})

    bundle = {k: v for k, v in BUNDLE.items() if k != "reference/week6.html"}
    bundle["slides/week2.html"] = "<title>Week 2 · Functions — MTR Slides</title>"
    r = admin.put(f"/api/courses/{course}/bundle",
                  files={"bundle": ("b.zip", _zip(bundle, folder=None), "application/zip")})
    assert r.json()["materials_added"] == 1 and r.json()["materials_removed"] == 1
    mats = _materials(admin, course)
    assert "Step-through|book" in mats and mats["Step-through|book"]["id"] == tool["id"]
    assert "Reference · Linux & Git|tools" not in mats


def test_rejects_unsafe_zip(login, grant):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../evil.html", "x")
    r = login("admin").post("/api/courses", data={"title": "x"},
                            files={"bundle": ("b.zip", buf.getvalue(), "application/zip")})
    assert r.status_code == 400
    r = login("admin").post("/api/courses", data={"title": "x"},
                            files={"bundle": ("b.zip", b"not a zip", "application/zip")})
    assert r.status_code == 400


def test_build_course_shelf_by_shelf(login, grant):
    grant("Member", "courses.view")
    admin, member = login("admin"), login("comp_member")
    r = admin.post("/api/courses", data={"title": "Electronics"})
    assert r.status_code == 201, r.text
    cid = r.json()["id"]

    def add(kind, **kw):
        files = kw.pop("files", None)
        return admin.post(f"/api/courses/{cid}/materials", data={"kind": kind, **kw}, files=files)

    slides = add("slides", files={"file": ("week3-ohm.html", "<title>Week 3 · Ohm's law — Lab</title>".encode(), "text/html")})
    assert slides.status_code == 201, slides.text
    assert (slides.json()["unit_label"], slides.json()["title"]) == ("Week 3", "Ohm's law")
    book = add("book", title="Chapter one", unit_label="Week 1", files={"file": ("ch1.pdf", b"%PDF-1", "application/pdf")})
    assert (book.json()["unit"], book.json()["media_type"]) == (1, "application/pdf")
    # same name twice never overwrites
    again = add("book", files={"file": ("ch1.pdf", b"%PDF-2", "application/pdf")})
    assert again.json()["path"] == "_uploads/book/ch1-2.pdf"
    answers = add("answers", files={"file": ("sol.html", b"<p>42</p>", "text/html")})
    assert answers.json()["is_released"] is False
    for i in range(3):  # as many tools as wanted, files or links
        assert add("tools", title=f"Sim {i}", url=f"https://example.com/{i}").status_code == 201
    assert add("tools", url="javascript:alert(1)").status_code == 400
    assert add("tools").status_code == 400  # neither file nor link

    detail = member.get(f"/api/courses/{cid}").json()
    assert detail["counts"] == {"slides": 1, "book": 2, "tasks": 0, "answers": 1, "tools": 3}
    link = next(m for m in detail["materials"] if m["title"] == "Sim 0")
    assert link["is_link"] and link["url"] == "https://example.com/0"
    assert member.get(f"/api/courses/{cid}/files/_uploads/answers/sol.html").status_code == 403
    assert member.get(f"/api/courses/{cid}/files/_uploads/book/ch1.pdf").content == b"%PDF-1"

    # editable after the course is up: replace a file, edit a link, delete
    bid = book.json()["id"]
    r = admin.put(f"/api/courses/{cid}/materials/{bid}/file", files={"file": ("ch1-v2.pdf", b"%PDF-new", "application/pdf")})
    assert r.status_code == 200
    assert member.get(f"/api/courses/{cid}/files/{r.json()['path']}").content == b"%PDF-new"
    assert member.get(f"/api/courses/{cid}/files/_uploads/book/ch1.pdf").status_code == 404
    admin.patch(f"/api/courses/{cid}/materials/{link['id']}", json={"external_url": "https://example.org/x"})
    assert admin.delete(f"/api/courses/{cid}/materials/{slides.json()['id']}").status_code == 204
    detail = member.get(f"/api/courses/{cid}").json()
    assert detail["counts"]["slides"] == 0
    assert any(m["url"] == "https://example.org/x" for m in detail["materials"])
    assert member.get(f"/api/courses/{cid}/files/_uploads/slides/week3-ohm.html").status_code == 404


def test_bundle_reupload_keeps_shelf_uploads(login, course):
    admin = login("admin")
    admin.post(f"/api/courses/{course}/materials", data={"kind": "tools", "title": "Extra"},
               files={"file": ("extra.pdf", b"%PDF", "application/pdf")})
    admin.post(f"/api/courses/{course}/materials", data={"kind": "tools", "url": "https://example.com"})
    admin.put(f"/api/courses/{course}/bundle", files={"bundle": ("b.zip", _zip(BUNDLE), "application/zip")})
    titles = {m["title"] for m in admin.get(f"/api/courses/{course}").json()["materials"]}
    assert {"Extra", "example.com"} <= titles
    assert admin.get(f"/api/courses/{course}/files/_uploads/tools/extra.pdf").status_code == 200


def test_office_file_gets_inline_pdf_preview(login, grant):
    """An uploaded office file is rendered to a cached PDF the viewer shows
    inline; a held-back one's rendition is refused to learners like its source.
    Skipped where LibreOffice isn't installed (e.g. CI without it)."""
    from app.domains.courses import preview
    if not preview.available():
        pytest.skip("LibreOffice not installed")

    grant("Member", "courses.view")
    admin, member = login("admin"), login("comp_member")
    cid = admin.post("/api/courses", data={"title": "Office"}).json()["id"]
    csv = b"name,score\nAla,10\nBob,7\n"

    slides = admin.post(f"/api/courses/{cid}/materials",
                        data={"kind": "slides"},
                        files={"file": ("grades.csv", csv, "text/csv")}).json()
    assert slides["preview_url"] and slides["preview_url"].endswith(".pdf")
    # the rendition serves as a real PDF, inline to learners
    r = member.get(slides["preview_url"])
    assert r.status_code == 200 and r.content[:5] == b"%PDF-"
    assert r.headers["content-type"].startswith("application/pdf")

    # a held-back office file's rendition is refused to learners, same as its source
    admin.post(f"/api/courses/{cid}/materials",
               data={"kind": "answers"},
               files={"file": ("key.csv", csv, "text/csv")})
    seen = next(m for m in member.get(f"/api/courses/{cid}").json()["materials"]
                if m["kind"] == "answers")
    assert seen["preview_url"] is None  # not surfaced to the learner while held back
    rendition = f"/api/courses/{cid}/files/_previews/_uploads/answers/key.csv.pdf"
    assert member.get(rendition).status_code == 403
    assert admin.get(rendition).status_code == 200
