"""Home dashboard aggregation: the me-scoped triage buckets (overdue / today /
this-week / needs-review / waiting-on-you) and the all-clear state."""


def _dash(login, who):
    r = login(who).get("/api/dashboard")
    assert r.status_code == 200, r.text
    return r.json()


def _task(login, who, assignee_key, org, title, due):
    r = login(who).post("/api/tasks", json={
        "title": title, "assignee_ids": [org[assignee_key].id], "due_date": due,
    })
    assert r.status_code == 201, r.text
    return r.json()[0]


def _counts(dash):
    return {s["key"]: s["count"] for s in dash["stats"]}


def test_buckets_split_by_urgency(login, org):
    # cto assigns sw_emp three dated tasks: overdue, today, this week
    _task(login, "cto", "sw_emp", org, "Late thing", "2020-01-01")   # far past → overdue
    _task(login, "cto", "sw_emp", org, "Today thing", __import__("datetime").date.today().isoformat())
    soon = (__import__("datetime").date.today() + __import__("datetime").timedelta(days=3)).isoformat()
    _task(login, "cto", "sw_emp", org, "Soon thing", soon)

    d = _dash(login, "sw_emp")
    counts = _counts(d)
    assert counts["overdue"] == 1
    assert counts["today"] == 1
    assert counts["week"] == 1
    assert d["all_clear"] is False
    keys = {s["key"] for s in d["sections"]}
    assert {"overdue", "today", "week"} <= keys
    # the overdue tile is flagged danger; the others aren't
    overdue_stat = next(s for s in d["stats"] if s["key"] == "overdue")
    assert overdue_stat["tone"] == "danger"


def test_all_clear_when_nothing_pending(login, org):
    # media_mgr has no tasks assigned and nothing waiting
    d = _dash(login, "media_mgr")
    assert d["all_clear"] is True
    assert d["sections"] == []
    assert all(s["count"] == 0 for s in d["stats"])


def test_waiting_on_you_from_work_request(login, org):
    # sw_emp requests work from cfo (up/across — not in sw_emp's subtree)
    r = login("sw_emp").post("/api/requests", json={
        "recipient_id": org["cfo"].id, "title": "Please approve budget",
    })
    assert r.status_code == 201, r.text
    d = _dash(login, "cfo")
    assert _counts(d)["waiting"] == 1
    waiting = next(s for s in d["sections"] if s["key"] == "waiting")
    assert waiting["items"][0]["source"] == "request"
    assert waiting["items"][0]["action"] == "Respond"


def test_needs_review_for_reviewer(login, org):
    # cto assigns sw_emp a task; sw_emp works and submits it for review
    task = _task(login, "cto", "sw_emp", org, "Build harness", None)
    assert login("sw_emp").patch(f"/api/tasks/{task['id']}/status",
                                 json={"status": "in_progress"}).status_code == 200
    assert login("sw_emp").patch(f"/api/tasks/{task['id']}/status",
                                 json={"status": "submitted"}).status_code == 200
    # the assigner (cto) sees it in their review queue
    d = _dash(login, "cto")
    assert d["is_reviewer"] is True
    assert _counts(d)["review"] == 1
    review = next(s for s in d["sections"] if s["key"] == "review")
    assert review["items"][0]["action"] == "Review"
    # the worker (sw_emp) does NOT see it as something to review
    assert _counts(_dash(login, "sw_emp")).get("review", 0) == 0
