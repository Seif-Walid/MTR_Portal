"""The public people endpoint: the real org chart as titles + names, nothing
else, readable without signing in."""

from app.domains.positions.models import Position, PositionOccupant


def test_people_lists_real_seats_with_names_only(client, org, db_session):
    db = db_session
    root = Position(title="President")
    db.add(root)
    db.flush()
    lead = Position(title="Software Lead", parent_id=root.id, is_technical=True)
    hat = Position(title="Sumo PM", parent_id=root.id, role_template_id=None)
    db.add_all([lead, hat])
    db.flush()
    hat.role_template_id = 999  # an automatic role seat — must not appear
    db.add_all([
        PositionOccupant(position_id=root.id, user_id=org["ceo"].id),
        PositionOccupant(position_id=lead.id, user_id=org["cto"].id),
        PositionOccupant(position_id=lead.id, user_id=org["sw_emp"].id),
    ])
    org["sw_emp"].is_active = False
    db.commit()

    r = client.get("/api/public/people")
    assert r.status_code == 200
    tree = r.json()
    assert [n["title"] for n in tree] == ["President"]
    assert tree[0]["people"] == [{"name": org["ceo"].full_name}]
    child = tree[0]["children"]
    assert [c["title"] for c in child] == ["Software Lead"]
    assert child[0]["technical"] is True
    assert child[0]["people"] == [{"name": org["cto"].full_name}]  # inactive dropped
    assert "email" not in r.text and "@" not in r.text
