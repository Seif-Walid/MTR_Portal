"""Assigning a task emails the assignee, once the assignment is committed."""

import pytest

from app.domains.notifications import service as notifications
from tests.conftest import make_task


@pytest.fixture()
def outbox(monkeypatch):
    sent: list[tuple[str, str, str, str]] = []
    # deliver inline so the test can see what went out
    monkeypatch.setattr(notifications, "_start_delivery", lambda batch: sent.extend(batch))
    return sent


def test_assigning_a_task_emails_the_assignee(login, org, outbox):
    r = login("mech_lead").post(
        "/api/tasks",
        json={
            "title": "Wire the arm",
            "description": "Use the new harness",
            "assignee_ids": [org["mech_emp"].id],
            "due_date": "2026-12-01",
        },
    )
    assert r.status_code == 201, r.text
    task_id = r.json()[0]["id"]
    assert len(outbox) == 1
    to, subject, text, html = outbox[0]
    assert to == org["mech_emp"].email
    assert subject == "New task: Wire the arm"
    assert org["mech_lead"].full_name in text
    assert "Use the new harness" in text
    assert "Due: Tue 01 Dec 2026" in text
    assert f"/tasks?task={task_id}" in text and f"/tasks?task={task_id}" in html


def test_multi_assignee_task_emails_each_person(login, org, outbox):
    r = login("mech_lead").post(
        "/api/tasks", json={"title": "Team job", "assignee_ids": [org["mech_emp"].id]}
    )
    assert r.status_code == 201
    make_task(login, "cto", org, "sw_emp")
    assert {to for to, *_ in outbox} == {org["mech_emp"].email, org["sw_emp"].email}


def test_failed_assignment_sends_nothing(login, org, outbox):
    # cfo is not above mech_emp, so the assignment is refused
    r = login("cfo").post(
        "/api/tasks", json={"title": "nope", "assignee_ids": [org["mech_emp"].id]}
    )
    assert r.status_code in (403, 404)
    assert outbox == []


def test_assignee_without_email_is_skipped(login, org, outbox, db_session):
    org["mech_emp"].email = None
    db_session.commit()
    make_task(login, "mech_lead", org, "mech_emp")
    assert outbox == []
