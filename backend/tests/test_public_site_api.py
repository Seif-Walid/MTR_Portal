"""What the public website reads beyond the Hall of Fame: which seats it lists
on its People page and what each person coached, which events are running and
recruiting, and applications filed against one of those events."""

from app.domains.applications.models import Application
from app.domains.events.models import Event
from app.domains.positions.models import Position, PositionOccupant
from tests.conftest import ensure_position, seat_role, setup_role_templates
from tests.test_applications import FORM


def test_hidden_seats_drop_out_but_their_sub_seats_move_up(client, org, db_session):
    db = db_session
    root = Position(title="CEO")
    db.add(root)
    db.flush()
    lead = Position(title="Software Lead ", parent_id=root.id)
    db.add(lead)
    db.flush()
    roster = Position(title="Software member", parent_id=lead.id, on_website=False)
    db.add(roster)
    db.flush()
    nested = Position(title="Firmware Lead", parent_id=roster.id)
    db.add(nested)
    db.flush()
    db.add_all([
        PositionOccupant(position_id=lead.id, user_id=org["cto"].id),
        PositionOccupant(position_id=roster.id, user_id=org["sw_emp"].id),
    ])
    db.commit()

    tree = client.get("/api/public/people").json()
    software = tree[0]["children"][0]
    assert software["title"] == "Software Lead"  # trimmed
    assert [c["title"] for c in software["children"]] == ["Firmware Lead"]
    assert org["sw_emp"].full_name not in str(tree)


def test_people_carry_what_they_coached(client, org, login):
    admin = login("admin")
    setup_role_templates(admin, pm=True, team_lead=True)
    root = ensure_position(admin)
    r = admin.post("/api/org/positions", json={"title": "CTO", "parent_id": root,
                                               "occupant_ids": [org["cto"].id]})
    assert r.status_code == 201, r.text
    ev = admin.post("/api/events", json={"name": "MATE ROV 2027", "start_date": "2026-09-01",
                                         "role_root_position_id": root}).json()
    seat_role(admin, ev, [org["cto"].id])
    cat = admin.post(f"/api/events/{ev['id']}/categories", json={"name": "Pioneers"}).json()
    team = admin.post(f"/api/events/categories/{cat['id']}/teams",
                      json={"name": "Software"}).json()
    seat_role(admin, team, [org["cto"].id])

    def coached():
        tree = client.get("/api/public/people").json()
        found = []

        def walk(nodes):
            for n in nodes:
                for p in n["people"]:
                    if p["name"] == org["cto"].full_name:
                        found.extend(p["coached"])
                walk(n["children"])
        walk(tree)
        return found

    seats = coached()
    assert {(s["as"], s["event"], s["team"]) for s in seats} == {
        ("PM", "MATE ROV 2027", None),
        ("Lead", "MATE ROV 2027", "Software"),
    }
    assert all(s["active"] and s["year"] == 2026 for s in seats)

    # archiving takes the seats off the chart, but the record keeps the credit
    assert admin.patch(f"/api/events/{ev['id']}", json={"status": "archived"}).status_code == 200
    seats = coached()
    assert {(s["as"], s["team"]) for s in seats} == {("PM", None), ("Lead", "Software")}
    assert not any(s["active"] for s in seats)


def test_events_list_running_events_and_recruiting(client, org, login, db_session):
    admin = login("admin")
    root = ensure_position(admin)
    r = admin.post("/api/events", json={
        "name": "MATE ROV 2027", "applications_open": True,
        "public_summary": "Build an underwater robot.", "description": "internal notes",
        "role_root_position_id": root,
    })
    assert r.status_code == 201, r.text
    assert r.json()["applications_open"] is True
    other = admin.post("/api/events", json={"name": "Robotiada"}).json()
    done = admin.post("/api/events", json={"name": "Old one", "applications_open": True}).json()
    admin.patch(f"/api/events/{done['id']}", json={"status": "archived"})

    rows = client.get("/api/public/events").json()
    by_name = {e["name"]: e for e in rows}
    assert set(by_name) == {"MATE ROV 2027", "Robotiada"}  # archived left out
    assert by_name["MATE ROV 2027"]["applicationsOpen"] is True
    assert by_name["MATE ROV 2027"]["summary"] == "Build an underwater robot."
    assert by_name["Robotiada"]["applicationsOpen"] is False
    assert "internal notes" not in str(rows)
    # archiving closed it
    assert db_session.get(Event, done["id"]).applications_open is False

    # and a manager can open / reword it later
    r = admin.patch(f"/api/events/{other['id']}", json={"applications_open": True, "public_summary": " "})
    assert r.json()["applications_open"] is True and r.json()["public_summary"] is None


def test_applying_to_an_event(client, org, login, db_session):
    admin = login("admin")
    root = ensure_position(admin)
    open_ev = admin.post("/api/events", json={"name": "MATE ROV 2027", "applications_open": True,
                                              "role_root_position_id": root}).json()
    closed = admin.post("/api/events", json={"name": "Robotiada"}).json()

    r = client.post("/api/public/applications", json={**FORM, "event_id": closed["id"]})
    assert r.status_code == 400
    r = client.post("/api/public/applications", json={**FORM, "event_id": 99999})
    assert r.status_code == 400

    assert client.post("/api/public/applications", json={**FORM, "event_id": open_ev["id"]}).status_code == 201
    # a general application the same day is a second application, not an edit
    assert client.post("/api/public/applications", json=FORM).status_code == 201
    # resending for the same event still updates in place
    assert client.post("/api/public/applications",
                       json={**FORM, "event_id": open_ev["id"], "subteam": "software"}).status_code == 201
    rows = db_session.query(Application).order_by(Application.id).all()
    assert [(a.event_id, a.subteam) for a in rows] == [(open_ev["id"], "software"), (None, None)]

    listed = admin.get("/api/applications").json()
    assert {a["event_name"] for a in listed} == {"MATE ROV 2027", None}
