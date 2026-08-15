"""Event kinds (Event/Training/R&D/...) and per-kind automatic roles:
every kind reuses the event structure with its own labels, and a role
template can fire for one kind or all."""

from tests.conftest import ensure_position


def _kinds(login) -> dict[str, dict]:
    return {k["slug"]: k for k in login("admin").get("/api/events/kinds").json()}


def _template(login, *, title, event, kind_slug=None, who="admin"):
    body = {"title_template": title, "event": event}
    if kind_slug is not None:
        body["event_kind_id"] = _kinds(login)[kind_slug]["id"]
    r = login(who).post("/api/org/roles/templates", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _event(login, *, name, kind_slug, root=None, who="cto"):
    body = {"name": name, "kind_id": _kinds(login)[kind_slug]["id"]}
    if root is not None:
        body["role_root_position_id"] = root
    r = login(who).post("/api/events", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _tree_titles(login) -> set[str]:
    def walk(nodes):
        out = set()
        for n in nodes:
            out.add(n["title"])
            out |= walk(n["children"])
        return out
    return walk(login("admin").get("/api/org/tree").json())


# --- kind catalog + CRUD ---------------------------------------------------
def test_preset_kinds_exist_with_labels(login, org):
    kinds = _kinds(login)
    assert set(kinds) == {"competition", "training", "rnd"}
    assert kinds["training"]["event_label"] == "Training Season"
    assert kinds["training"]["team_label"] == "Group"
    assert kinds["rnd"]["event_label"] == "Topic"


def test_kind_crud_is_org_edit_gated(login, org):
    # a Lead (cto) lacks org.edit
    assert login("cto").post("/api/events/kinds", json={
        "name": "Workshop", "event_label": "Workshop"}).status_code == 403
    r = login("ceo").post("/api/events/kinds", json={  # ceo=Exec has org.edit
        "name": "Workshop", "event_label": "Workshop", "team_label": "Crew"})
    assert r.status_code == 201, r.text
    kind = r.json()
    assert kind["slug"] == "workshop" and kind["team_label"] == "Crew"

    # rename a label
    assert login("ceo").patch(f"/api/events/kinds/{kind['id']}",
                              json={"team_label": "Squad"}).status_code == 200
    assert _kinds(login)["workshop"]["team_label"] == "Squad"

    # empty kind deletes fine
    assert login("ceo").delete(f"/api/events/kinds/{kind['id']}").status_code == 204
    assert "workshop" not in _kinds(login)


def test_kind_with_events_cannot_be_deleted(login, org):
    _event(login, name="Summer Camp", kind_slug="training")
    training_id = _kinds(login)["training"]["id"]
    assert login("admin").delete(f"/api/events/kinds/{training_id}").status_code == 400


# --- per-kind automatic roles ----------------------------------------------
def test_roles_fire_only_for_their_kind(login, org):
    root = ensure_position(login("admin"))
    _template(login, title="{event} PM", event="event_created", kind_slug="competition")
    _template(login, title="{event} Season Lead", event="event_created", kind_slug="training")
    _template(login, title="{event} Observer", event="event_created", kind_slug=None)  # all kinds

    _event(login, name="RoboCup", kind_slug="competition", root=root)
    _event(login, name="Bootcamp", kind_slug="training")

    titles = _tree_titles(login)
    # event got its PM + the shared Observer, but NOT the training role
    assert "RoboCup PM" in titles
    assert "RoboCup Observer" in titles
    assert "RoboCup Season Lead" not in titles
    # training got its Season Lead + the shared Observer, but NOT the PM
    assert "Bootcamp Season Lead" in titles
    assert "Bootcamp Observer" in titles
    assert "Bootcamp PM" not in titles


def test_edit_template_can_change_its_kind(login, org):
    tpl = _template(login, title="{event} PM", event="event_created", kind_slug="competition")
    comp_id = _kinds(login)["competition"]["id"]
    assert tpl["event_kind_id"] == comp_id

    training_id = _kinds(login)["training"]["id"]
    # switch to training
    r = login("admin").patch(f"/api/org/roles/templates/{tpl['id']}",
                             json={"event_kind_id": training_id, "set_event_kind": True})
    assert r.status_code == 200, r.text
    assert r.json()["event_kind_id"] == training_id

    # widen to all kinds
    r = login("admin").patch(f"/api/org/roles/templates/{tpl['id']}",
                             json={"event_kind_id": None, "set_event_kind": True})
    assert r.status_code == 200, r.text
    assert r.json()["event_kind_id"] is None


def test_edit_template_can_change_its_when_event(login, org):
    tpl = _template(login, title="{team} Lead", event="team_created")
    assert tpl["event"] == "team_created"

    r = login("admin").patch(f"/api/org/roles/templates/{tpl['id']}",
                             json={"event": "event_created"})
    assert r.status_code == 200, r.text
    assert r.json()["event"] == "event_created"

    r = login("admin").patch(f"/api/org/roles/templates/{tpl['id']}",
                             json={"event": "nonsense"})
    assert r.status_code == 400, r.text


def test_edit_without_event_leaves_when_untouched(login, org):
    tpl = _template(login, title="{team} Lead", event="team_created")
    r = login("admin").patch(f"/api/org/roles/templates/{tpl['id']}",
                             json={"title_template": "{team} Boss"})
    assert r.status_code == 200, r.text
    assert r.json()["event"] == "team_created"


def test_edit_without_set_event_kind_leaves_kind_untouched(login, org):
    comp_id = _kinds(login)["competition"]["id"]
    tpl = _template(login, title="{event} PM", event="event_created", kind_slug="competition")
    # a title-only edit (no set_event_kind) must not wipe the kind to "all"
    r = login("admin").patch(f"/api/org/roles/templates/{tpl['id']}",
                             json={"title_template": "{event} Lead"})
    assert r.status_code == 200, r.text
    assert r.json()["event_kind_id"] == comp_id


def test_chain_stays_within_a_kind(login, org):
    """A training team role chains under the training top role, never under a
    event role, even though both react to the same event triggers."""
    root = ensure_position(login("admin"))
    _template(login, title="{event} PM", event="event_created", kind_slug="competition")
    _template(login, title="{event} Season Lead", event="event_created", kind_slug="training")
    _template(login, title="{team} Group Lead", event="team_created", kind_slug="training")

    def node(title):
        def walk(nodes):
            for n in nodes:
                if n["title"] == title:
                    return n
                found = walk(n["children"])
                if found:
                    return found
            return None
        return walk(login("admin").get("/api/org/tree").json())

    training = _event(login, name="Bootcamp", kind_slug="training", root=root, who="admin")
    cat = login("admin").post(f"/api/events/{training['id']}/categories", json={"name": "Beginners"}).json()
    login("admin").post(f"/api/events/categories/{cat['id']}/teams", json={"name": "Alpha"})

    season = node("Bootcamp Season Lead")
    group = node("Alpha Group Lead")
    assert season is not None and season["parent_id"] == root
    assert group is not None and group["parent_id"] == season["id"]  # chained within Training
