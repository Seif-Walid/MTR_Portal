"""Web Push: devices subscribe, every notification is pushed to them after
commit, dead devices are forgotten, and nothing leaks across origins."""

import json

import pytest
from pywebpush import WebPushException

from app.core.config import settings
from app.domains.notifications import push
from app.domains.notifications.models import PushSubscription
from tests.conftest import make_task

FCM = "https://fcm.googleapis.com/fcm/send/abc123"
SUB = {"endpoint": FCM, "keys": {"p256dh": "BPk" + "x" * 84, "auth": "a" * 22}}


class FakeSender:
    def __init__(self, fail_with: int | None = None):
        self.calls: list[dict] = []
        self.fail_with = fail_with

    def __call__(self, **kw):
        self.calls.append(kw)
        if self.fail_with:
            class R:
                status_code = self.fail_with
            raise WebPushException("gone", response=R())


def test_key_is_made_once_and_public(login):
    me = login("ceo")
    k1 = me.get("/api/notifications/push/key").json()["public_key"]
    k2 = me.get("/api/notifications/push/key").json()["public_key"]
    assert k1 == k2 and len(k1) == 87  # 65-byte P-256 point, base64url


def test_subscribe_rejects_non_push_hosts(login):
    me = login("ceo")
    for bad in ("http://fcm.googleapis.com/x", "https://evil.example.com/x", "https://169.254.169.254/x",
                "https://fcm.googleapis.com.evil.com/x"):
        r = me.post("/api/notifications/push/subscribe", json={**SUB, "endpoint": bad})
        assert r.status_code == 400, bad


def test_subscribe_list_remove(login, db_session):
    me = login("ceo")
    assert me.post("/api/notifications/push/subscribe", json=SUB,
                   headers={"user-agent": "Mozilla/5.0 (Linux; Android 14) Chrome/130 Mobile"}).status_code == 200
    # same endpoint again: still one device
    me.post("/api/notifications/push/subscribe", json=SUB)
    devices = me.get("/api/notifications/push/devices").json()
    assert len(devices) == 1
    # someone else can't remove it
    login("cfo").delete(f"/api/notifications/push/devices/{devices[0]['id']}")
    assert len(me.get("/api/notifications/push/devices").json()) == 1
    me.delete(f"/api/notifications/push/devices/{devices[0]['id']}")
    assert me.get("/api/notifications/push/devices").json() == []


def test_device_name(login):
    me = login("ceo")
    me.post("/api/notifications/push/subscribe", json=SUB,
            headers={"user-agent": "Mozilla/5.0 (Linux; Android 14) AppleWebKit Chrome/130 Mobile Safari"})
    assert me.get("/api/notifications/push/devices").json()[0]["device"] == "Chrome on Android"


def test_task_assignment_is_pushed_after_commit(login, org, db_session, pushes):
    login("mech_emp").post("/api/notifications/push/subscribe", json=SUB)
    task = make_task(login, "ceo", org, "mech_emp", title="Fix the gripper")
    mine = [p for uid, p in pushes if uid == org["mech_emp"].id]
    assert mine and mine[0]["url"] == f"/tasks?task={task['id']}"
    assert mine[0]["title"] == "New task · Fix the gripper"
    assert "Fix the gripper" not in mine[0]["body"]  # not repeated
    assert "assigned you a task" in mine[0]["body"]
    assert isinstance(mine[0]["id"], int)  # lets the device mark exactly this one read

    sender = FakeSender()
    assert push.deliver(db_session, pushes, sender=sender) >= 1
    sent = json.loads(sender.calls[0]["data"])
    assert sent["title"].startswith("New task") and sent["unread"] >= 1
    assert sender.calls[0]["subscription_info"]["endpoint"] == FCM


def test_gone_device_is_forgotten(login, org, db_session):
    login("ceo").post("/api/notifications/push/subscribe", json=SUB)
    push.deliver(db_session, [(org["ceo"].id, {"title": "t", "body": "b", "url": "/", "tag": "x"})],
                 sender=FakeSender(fail_with=410))
    assert db_session.query(PushSubscription).count() == 0


def test_other_origin_devices_are_never_pushed(login, org, db_session, monkeypatch):
    """A staging server with a copy of the prod DB must not ping prod devices."""
    login("ceo").post("/api/notifications/push/subscribe", json=SUB)
    monkeypatch.setattr(settings, "frontend_url", "https://staging.example.com")
    sender = FakeSender()
    push.deliver(db_session, [(org["ceo"].id, {"title": "t", "body": "b", "url": "/", "tag": "x"})], sender=sender)
    assert sender.calls == []


@pytest.mark.parametrize("ep,ok", [
    ("https://fcm.googleapis.com/fcm/send/x", True),
    ("https://updates.push.services.mozilla.com/wpush/v2/x", True),
    ("https://web.push.apple.com/x", True),
    ("https://wns2-par02p.notify.windows.com/w/?token=x", True),
    ("https://example.com/x", False),
    ("ftp://fcm.googleapis.com/x", False),
])
def test_endpoint_allowlist(ep, ok):
    assert push.endpoint_allowed(ep) is ok


def test_task_facts_in_body(login, org, pushes):
    r = login("ceo").post("/api/tasks", json={
        "title": "Order motors", "assignee_ids": [org["mech_emp"].id],
        "due_date": "2026-11-30", "priority": "high",
    })
    assert r.status_code == 201, r.text
    body = [p for uid, p in pushes if uid == org["mech_emp"].id][0]["body"]
    assert body.splitlines()[-1] == "Due Mon 30 Nov · High priority"


def test_attachment_picks_side_picture(login, org, db_session):
    from app.domains.tasks.models import TaskAttachment

    task = make_task(login, "ceo", org, "mech_emp", title="Wire it")
    assert push.attachment_for(db_session, task["id"]) is None  # -> logo on the side

    def add(**kw):
        db_session.add(TaskAttachment(task_id=task["id"], uploaded_by_id=org["ceo"].id, **kw))
        db_session.commit()
        return push.attachment_for(db_session, task["id"])

    assert add(kind="file", filename="photo.jpg", content_type="image/jpeg", size=2000, stored_name="a1")["kind"] == "image"
    assert add(kind="file", filename="huge.png", content_type="image/png", size=50_000_000, stored_name="a2")["kind"] == "file"
    assert add(kind="file", filename="spec.pdf", content_type="application/pdf", size=10, stored_name="a3")["kind"] == "pdf"
    att = add(kind="link", filename="EasyEDA", url="https://easyeda.com/x", content_type="text/uri-list")
    assert att == {"kind": "link", "name": "EasyEDA"}


def test_attachment_named_in_pushed_body(login, org, db_session):
    from app.domains.tasks.models import TaskAttachment

    login("mech_emp").post("/api/notifications/push/subscribe", json=SUB)
    task = make_task(login, "ceo", org, "mech_emp", title="Wire it")
    db_session.add(TaskAttachment(task_id=task["id"], uploaded_by_id=org["ceo"].id, kind="file",
                                  filename="board.png", content_type="image/png", size=900, stored_name="b1"))
    db_session.commit()
    sender = FakeSender()
    push.deliver(db_session, [(org["mech_emp"].id, {"title": "t", "body": "b", "url": "/", "tag": "x", "task_id": task["id"]})], sender=sender)
    data = json.loads(sender.calls[0]["data"])
    assert data["body"].endswith("📎 board.png")
    assert data["attachment"]["src"].startswith("/api/tasks/attachments/")
