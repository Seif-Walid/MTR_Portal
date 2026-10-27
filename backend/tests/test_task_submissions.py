"""Task submissions beyond small files: links (GitHub, EasyEDA, CAD share
links) and files sent straight from the browser to the connected Google
Drive. Drive itself is faked — what's tested is the portal's side."""

import pytest

from app.domains.drive import service as drive
from app.domains.drive.models import DriveConnection
from tests.conftest import make_task


def test_link_submission(login, org):
    task = make_task(login, "cto", org, "sw_emp")
    sw = login("sw_emp")
    r = sw.post(f"/api/tasks/{task['id']}/links",
                json={"url": "https://github.com/mtr/rov/pull/12", "title": "PR #12"})
    assert r.status_code == 201, r.text
    assert r.json()["kind"] == "link" and r.json()["url"].endswith("/pull/12")
    assert sw.post(f"/api/tasks/{task['id']}/links", json={"url": "javascript:alert(1)"}).status_code == 400
    # someone unrelated can't attach to it
    assert login("fin_emp").post(f"/api/tasks/{task['id']}/links",
                                 json={"url": "https://x.example"}).status_code in (403, 404)
    # the assigner follows the link through the portal
    res = login("cto").get(f"/api/tasks/attachments/{r.json()['id']}", follow_redirects=False)
    assert res.status_code in (302, 307) and res.headers["location"].endswith("/pull/12")


def test_drive_upload_needs_a_connection(login, org):
    task = make_task(login, "cto", org, "sw_emp")
    r = login("sw_emp").post(f"/api/tasks/{task['id']}/drive-uploads",
                             json={"filename": "arm.step", "size": 10})
    assert r.status_code == 409


@pytest.fixture()
def fake_drive(db_session, monkeypatch, org):
    db_session.add(DriveConnection(email="club@example.com", refresh_token="r", root_folder_id="root",
                                   connected_by_id=org["admin"].id))
    db_session.commit()
    files: dict[str, dict] = {}
    opened: list[dict] = []

    def start_upload(conn, *, folder_id, name, content_type, size, origin, app_properties):
        opened.append({"folder": folder_id, "name": name, "origin": origin})
        fid = f"file{len(files) + 1}"
        files[fid] = {"id": fid, "name": name, "size": str(size), "mimeType": content_type,
                      "appProperties": app_properties}
        return f"https://upload.example/{fid}"

    monkeypatch.setattr(drive, "folder_path", lambda db, conn, parts: "/".join(parts))
    monkeypatch.setattr(drive, "start_upload", start_upload)
    monkeypatch.setattr(drive, "file_meta", lambda conn, fid: files[fid])
    monkeypatch.setattr(drive, "stream", lambda conn, fid: iter([b"STEP", b"DATA"]))
    return {"files": files, "opened": opened}


def test_drive_upload_flow(login, org, fake_drive):
    task = make_task(login, "cto", org, "sw_emp")
    sw = login("sw_emp")
    r = sw.post(f"/api/tasks/{task['id']}/drive-uploads",
                json={"filename": "arm.step", "size": 900 * 1024 * 1024},
                headers={"Origin": "http://localhost:5179"})
    assert r.status_code == 200, r.text
    assert r.json()["upload_url"] == "https://upload.example/file1"
    assert fake_drive["opened"][0] == {"folder": f"Tasks/{org['sw_emp'].full_name}",
                                       "name": "arm.step", "origin": "http://localhost:5179"}

    done = sw.post(f"/api/tasks/{task['id']}/drive-uploads/complete", json={"file_id": "file1"})
    assert done.status_code == 201, done.text
    att = done.json()
    assert att["kind"] == "drive" and att["filename"] == "arm.step" and att["size"] == 900 * 1024 * 1024

    body = login("cto").get(f"/api/tasks/attachments/{att['id']}")
    assert body.status_code == 200 and body.content == b"STEPDATA"
    assert "arm.step" in body.headers["content-disposition"]


def test_drive_upload_limits_and_ownership(login, org, fake_drive):
    task = make_task(login, "cto", org, "sw_emp")
    other = make_task(login, "cto", org, "sw_emp")
    sw = login("sw_emp")
    too_big = sw.post(f"/api/tasks/{task['id']}/drive-uploads",
                      json={"filename": "huge.zip", "size": 5 * 1024 ** 3})
    assert too_big.status_code == 413
    sw.post(f"/api/tasks/{other['id']}/drive-uploads", json={"filename": "a.step", "size": 5})
    # a file opened for one task can't be claimed by another
    assert sw.post(f"/api/tasks/{task['id']}/drive-uploads/complete",
                   json={"file_id": "file1"}).status_code == 400


def test_drive_status_and_connect_gate(login, org):
    assert login("sw_emp").get("/api/drive/status").json()["connected"] is False
    assert login("sw_emp").get("/api/drive/connect", follow_redirects=False).status_code == 403
    r = login("admin").get("/api/drive/connect", follow_redirects=False)
    assert r.status_code in (302, 307)
    assert "drive.file" in r.headers["location"] and "state=drive." in r.headers["location"]


def test_connect_callback_stores_the_drive(login, org, monkeypatch, db_session):
    """The Drive grant returns through the sign-in callback; a drive.* state
    routes it to the connection instead of signing anyone in."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "google_client_id", "id")
    monkeypatch.setattr(settings, "google_client_secret", "secret")
    seen = {}
    monkeypatch.setattr(drive, "finish_connect",
                        lambda db, code, uid: seen.update(code=code, uid=uid))
    admin = login("admin")
    start = admin.get("/api/drive/connect", follow_redirects=False)
    state = start.headers["location"].split("state=")[1].split("&")[0]
    admin.client.cookies.set("g_oauth_state", state)
    r = admin.get(f"/api/auth/google/callback?code=abc&state={state}", follow_redirects=False)
    assert r.headers["location"].endswith("/admin/users?drive=connected")
    assert seen == {"code": "abc", "uid": org["admin"].id}
