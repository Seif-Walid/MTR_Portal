"""Calendar aggregation: per-source scoping (me vs general), privilege
gating, and the date window."""

from tests.conftest import ensure_position, seat_role, setup_role_templates


def _cal(login, who, scope="general", sources="tasks", **params):
    q = {"scope": scope, "sources": sources, **params}
    r = login(who).get("/api/calendar", params=q)
    assert r.status_code == 200, r.text
    return r.json()


def _task(login, who, assignee_key, org, title, due):
    r = login(who).post("/api/tasks", json={
        "title": title, "assignee_ids": [org[assignee_key].id], "due_date": due,
    })
    assert r.status_code == 201, r.text
    return r.json()[0]


def test_tasks_me_vs_general(login, org):
    # cto assigns a dated task to sw_emp (a direct report)
    _task(login, "cto", "sw_emp", org, "Wire the harness", "2026-08-10")
    # cfo assigns a dated task to fin_emp — outside cto's subtree
    _task(login, "cfo", "fin_emp", org, "Close the books", "2026-08-11")

    # general (cto): sees own subtree — the harness task, not the finance one
    titles = {i["title"] for i in _cal(login, "cto", "general", "tasks")}
    assert "Wire the harness" in titles
    assert "Close the books" not in titles

    # me (sw_emp): only tasks assigned to/by them
    mine = _cal(login, "sw_emp", "me", "tasks")
    assert {i["title"] for i in mine} == {"Wire the harness"}
    assert mine[0]["source"] == "task" and mine[0]["start"] == "2026-08-10"


def test_source_selection_and_privilege_gating(login, org):
    _task(login, "cto", "sw_emp", org, "Dated task", "2026-08-10")
    # a task exists, but if 'tasks' isn't requested it isn't returned
    assert _cal(login, "cto", "general", "events") == []
    # a Member-tier user (student) has tasks.use, so their own dated task shows
    _task(login, "team_lead", "student", org, "Read the manual", "2026-08-12")
    assert {i["title"] for i in _cal(login, "student", "me", "tasks")} == {"Read the manual"}


def test_events_me_vs_general(login, org):
    admin = login("admin")
    setup_role_templates(admin, pm=True, member=True)
    root = ensure_position(admin)
    # an event with dates, created by cto
    r = login("cto").post("/api/events", json={
        "name": "MATE ROV", "start_date": "2026-09-01", "end_date": "2026-09-05",
        "role_root_position_id": root,
    })
    assert r.status_code == 201, r.text
    comp = r.json()
    cat = login("cto").post(f"/api/events/{comp['id']}/categories", json={"name": "Senior"})
    # cto must manage it to add a category — seat them as PM first
    seat_role(admin, comp, [org["cto"].id])
    cat = login("cto").post(f"/api/events/{comp['id']}/categories", json={"name": "Senior"}).json()
    team = login("cto").post(f"/api/events/categories/{cat['id']}/teams", json={"name": "Alpha"}).json()
    login("cto").post(f"/api/events/teams/{team['id']}/members", json={"user_id": org["student"].id})

    # general (anyone with events.view) sees the event as a span
    ev = [i for i in _cal(login, "cfo", "general", "events") if i["title"] == "MATE ROV"]
    assert ev and ev[0]["start"] == "2026-09-01" and ev[0]["end"] == "2026-09-05"
    assert ev[0]["source"] == "event"

    # me: the student participates (team member) → sees it; a bystander doesn't
    assert any(i["title"] == "MATE ROV" for i in _cal(login, "student", "me", "events"))
    assert _cal(login, "media_mgr", "me", "events") == []
    # the seated PM (cto) also counts as participating
    assert any(i["title"] == "MATE ROV" for i in _cal(login, "cto", "me", "events"))


def test_date_window_bounds_results(login, org):
    _task(login, "cto", "sw_emp", org, "August task", "2026-08-15")
    _task(login, "cto", "sw_emp", org, "October task", "2026-10-15")
    aug = {i["title"] for i in _cal(login, "cto", "general", "tasks",
                                    start="2026-08-01", end="2026-08-31")}
    assert aug == {"August task"}


def test_combined_sources_sorted_by_date(login, org):
    _task(login, "cto", "sw_emp", org, "Task A", "2026-08-20")
    admin = login("admin")
    setup_role_templates(admin, pm=True)
    root = ensure_position(admin)
    login("cto").post("/api/events", json={
        "name": "Early Cup", "start_date": "2026-08-05", "end_date": "2026-08-06",
        "role_root_position_id": root,
    })
    items = _cal(login, "cto", "general", "tasks,events")
    dates = [i["start"] for i in items]
    assert dates == sorted(dates)
    assert {i["source"] for i in items} == {"task", "event"}
