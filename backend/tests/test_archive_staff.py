"""Archiving an event keeps who held its role seats (PM, coach, lead, …): the
seats leave the org chart, the people stay on the event's record, and
reactivating seats them back. The archive is also organized by event kind."""

from tests.test_archive import _team_with_members
from tests.test_event_teams import _appoint_lead, _category, _comp, _team


def _staffed_event(login, org):
    """An event with a PM (cto, seated by _comp), a team lead and a member."""
    cid, team = _team_with_members(login, org, ["sw_emp"])
    _appoint_lead(login, team, org["team_lead"].id)
    return cid, team


def _archive(login, cid):
    r = login("cto").patch(f"/api/events/{cid}", json={"status": "archived"})
    assert r.status_code == 200, r.text


def test_archiving_keeps_the_seat_holders(login, org):
    cid, team = _staffed_event(login, org)
    _archive(login, cid)

    detail = login("comp_member").get(f"/api/archive/events/{cid}").json()
    assert [(s["role"], s["user_id"]) for s in detail["staff"]] == [("PM", org["cto"].id)]
    group = next(g for g in detail["groups"] if g["id"] == team["id"])
    assert [(s["role"], s["user_id"]) for s in group["staff"]] == [("Lead", org["team_lead"].id)]
    assert group["staff"][0]["name"] == org["team_lead"].full_name

    # the seats themselves are off the org chart
    tree = str(login("admin").get("/api/org/tree").json())
    assert "C PM" not in tree and "Team A Lead" not in tree


def test_seat_holder_sees_their_team_in_the_archive(login, org):
    cid, team = _staffed_event(login, org)
    _archive(login, cid)
    detail = login("team_lead").get(f"/api/archive/events/{cid}").json()
    assert team["name"] in detail["teams"]


def test_reactivating_seats_the_people_back(login, org):
    cid, team = _staffed_event(login, org)
    _archive(login, cid)

    assert login("cto").post(f"/api/archive/events/{cid}/reactivate").status_code == 200
    live = login("cto").get(f"/api/events/{cid}").json()
    assert [o["id"] for o in live["roles"][0]["occupants"]] == [org["cto"].id]
    live_team = live["categories"][0]["teams"][0]
    assert [o["id"] for o in live_team["roles"][0]["occupants"]] == [org["team_lead"].id]

    # archived again: recorded once, not twice
    _archive(login, cid)
    detail = login("cto").get(f"/api/archive/events/{cid}").json()
    assert len(detail["staff"]) == 1
    assert len(next(g for g in detail["groups"] if g["id"] == team["id"])["staff"]) == 1


def test_reactivating_from_the_events_page_restores_too(login, org):
    cid, _team = _staffed_event(login, org)
    _archive(login, cid)
    r = login("admin").patch(f"/api/events/{cid}", json={"status": "active"})
    assert r.status_code == 200, r.text
    live = login("cto").get(f"/api/events/{cid}").json()
    assert [o["id"] for o in live["roles"][0]["occupants"]] == [org["cto"].id]


def test_editor_records_staff_by_hand(login, org):
    cid = _comp(login, "cto").json()["id"]
    cat = _category(login, cid).json()
    team = _team(login, cat["id"]).json()
    _archive(login, cid)

    editor = login("admin")
    r = editor.post(f"/api/archive/events/{cid}/staff",
                 json={"role": "coach", "team_id": team["id"], "user_id": org["mech_emp"].id})
    assert r.status_code == 201, r.text
    r = editor.post(f"/api/archive/events/{cid}/staff", json={"role": "Mentor", "name": "Dr. Outside"})
    assert r.status_code == 201, r.text
    outside = r.json()
    assert outside["user_id"] is None and outside["name"] == "Dr. Outside"

    detail = editor.get(f"/api/archive/events/{cid}").json()
    assert ("Mentor", "Dr. Outside") in [(s["role"], s["name"]) for s in detail["staff"]]
    group = next(g for g in detail["groups"] if g["id"] == team["id"])
    assert [(s["role"], s["user_id"]) for s in group["staff"]] == [("coach", org["mech_emp"].id)]

    assert editor.delete(f"/api/archive/staff/{outside['id']}").status_code == 204
    detail = editor.get(f"/api/archive/events/{cid}").json()
    assert "Dr. Outside" not in [s["name"] for s in detail["staff"]]


def test_staff_edits_need_archive_edit(login, org):
    cid = _comp(login, "cto").json()["id"]
    _archive(login, cid)
    member = login("comp_member")
    assert member.post(f"/api/archive/events/{cid}/staff", json={"role": "x", "name": "y"}).status_code == 403
    rec = login("admin").post(f"/api/archive/events/{cid}/staff", json={"role": "x", "name": "y"}).json()
    assert member.delete(f"/api/archive/staff/{rec['id']}").status_code == 403


def test_staff_needs_a_person(login, org):
    cid = _comp(login, "cto").json()["id"]
    _archive(login, cid)
    r = login("admin").post(f"/api/archive/events/{cid}/staff", json={"role": "coach"})
    assert r.status_code == 400


def test_archive_is_sectioned_by_kind(login, org):
    kinds = {k["slug"]: k for k in login("admin").get("/api/events/kinds").json()}
    comp_id = _comp(login, "cto", name="Comp").json()["id"]
    r = login("admin").post("/api/events", json={"name": "Camp", "kind_id": kinds["training"]["id"]})
    assert r.status_code == 201, r.text
    training_id = r.json()["id"]
    _archive(login, comp_id)
    assert login("admin").patch(f"/api/events/{training_id}", json={"status": "archived"}).status_code == 200

    sections = {k["slug"]: k for k in login("comp_member").get("/api/archive/kinds").json()}
    assert sections["competition"]["count"] == 1 and sections["training"]["count"] == 1
    assert sections["rnd"]["count"] == 0

    only = login("comp_member").get(
        "/api/archive/events", params={"kind_id": kinds["training"]["id"]}
    ).json()
    assert [e["id"] for e in only] == [training_id]
    assert only[0]["kind_id"] == kinds["training"]["id"]
    assert only[0]["team_label"] == kinds["training"]["team_label"]


def test_reactivating_is_not_editing(login, org):
    """Whoever may create events may still reactivate one — but a finished
    event's record is history, editable only with archive.edit."""
    cid, team = _staffed_event(login, org)
    _archive(login, cid)
    cto = login("cto")  # Lead: events.create, no archive.edit
    detail = cto.get(f"/api/archive/events/{cid}").json()
    assert detail["event"]["can_manage"] is True and detail["event"]["can_edit"] is False
    assert cto.patch(f"/api/archive/events/{cid}", json={"full_name": "X"}).status_code == 403
    assert cto.patch(f"/api/archive/teams/{team['id']}", json={"award": "X"}).status_code == 403
    assert cto.post(f"/api/archive/events/{cid}/staff", json={"role": "x", "name": "y"}).status_code == 403
    staff_id = detail["staff"][0]["id"]
    assert cto.delete(f"/api/archive/staff/{staff_id}").status_code == 403

    # the top level always holds it
    assert login("admin").get(f"/api/archive/events/{cid}").json()["event"]["can_edit"] is True


def test_archive_edit_is_a_toggleable_privilege(login, org):
    cid, _team = _staffed_event(login, org)
    _archive(login, cid)
    admin = login("admin")
    assert "archive.edit" in {p["key"] for p in admin.get("/api/access/privileges").json()}

    lead = next(lvl for lvl in admin.get("/api/access/levels").json() if lvl["name"] == "Lead")
    r = admin.patch(f"/api/access/levels/{lead['id']}", json={"privileges": [*lead["privileges"], "archive.edit"]})
    assert r.status_code == 200, r.text

    cto = login("cto")
    assert cto.get(f"/api/archive/events/{cid}").json()["event"]["can_edit"] is True
    assert cto.patch(f"/api/archive/events/{cid}", json={"full_name": "X"}).status_code == 200
