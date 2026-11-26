"""Any page action as an assistant tool: find_actions searches the route
catalogue, portal_read runs GETs, portal_change dry-runs the real route as
the user (their permissions, nothing kept) and only runs on confirm."""

import json

from app.domains.ai import actions
from app.domains.inventory.models import InventoryItem

from tests.conftest import ensure_position


def _token(login, who="admin") -> dict:
    r = login(who).post("/api/ai/connect")
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _call(client, headers, tool, **arguments):
    r = client.post(f"/api/ai/tools/{tool}", json={"arguments": arguments}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _item(login, name="Arduino", quantity=5):
    r = login("admin").post("/api/inventory", json={"name": name, "quantity": quantity})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_catalogue_covers_page_actions_but_not_login_or_the_assistant():
    ops = {(o["method"], o["path"]) for o in actions.operations()}
    assert ("POST", "/api/finance/money-in/dues") in ops
    assert ("PATCH", "/api/tasks/{task_id}/status") in ops
    assert ("DELETE", "/api/inventory/{item_id}") in ops
    assert ("PUT", "/api/auth/me/profile") in ops
    for blocked in [("POST", "/api/auth/login"), ("POST", "/api/ai/actions/confirm"),
                    ("POST", "/api/courses"),  # file upload
                    ("POST", "/api/public/applications"), ("DELETE", "/api/drive")]:
        assert blocked not in ops, blocked


def test_find_actions_returns_the_route_and_its_body(client, login, org):
    out = _call(client, _token(login), "find_actions", query="record dues payment")
    dues = next(a for a in out["actions"] if a["path"] == "/api/finance/money-in/dues")
    assert dues["method"] == "POST"
    assert {"member_id", "amount"} <= set(dues["body"]["properties"])
    everything = _call(client, _token(login), "find_actions", query="")["actions"]
    assert len(everything) == len(actions.operations())


def test_body_keeps_fields_named_title_and_their_descriptions():
    ops = {(o["method"], o["path"]): o for o in actions.operations()}
    task = actions.describe(ops[("POST", "/api/tasks")], True)["body"]
    assert "title" in task["properties"] and "title" in task["required"]
    block = actions.describe(ops[("POST", "/api/timeblocks")], True)["body"]["properties"]
    assert "title" in block
    assert "Thursday=8" in block["weekday_mask"]["description"]


def test_hidden_meanings_reach_the_assistant():
    """Values whose meaning isn't obvious from the type must say so in the
    catalogue — the assistant never sees Python comments."""
    ops = {(o["method"], o["path"]): o for o in actions.operations()}

    def body(method, path):
        return actions.describe(ops[(method, path)], True)["body"]["properties"]

    assert "REPLACES" in body("PATCH", "/api/org/positions/{position_id}")["occupant_ids"]["description"]
    assert "EVERY" in body("POST", "/api/notifications/mark-read")["ids"]["description"]
    edit = actions.describe(ops[("PATCH", "/api/finance/entries/{kind}/{entry_id}")], True)
    assert "unit_cost" in edit["doc"] and "payee_party_id" in edit["doc"]
    tasks = actions.describe(ops[("GET", "/api/tasks")], True)["params"]
    status = next(p for p in tasks if p["name"] == "status_filter")
    assert "in_progress" in str(status)


def test_change_is_only_proposed_then_runs_on_confirm(client, login, org, db_session):
    item_id = _item(login)
    headers = _token(login)
    out = _call(client, headers, "portal_change", method="DELETE", path=f"/api/inventory/{item_id}",
                summary="Delete the Arduino")
    assert out["proposed"], out
    db_session.expire_all()
    assert db_session.get(InventoryItem, item_id) is not None  # dry run kept nothing
    pending = login("admin").get("/api/ai/actions").json()
    assert any("Delete the Arduino" in a["summary"] and f"/api/inventory/{item_id}" in a["summary"] for a in pending)

    r = login("admin").post("/api/ai/actions/confirm", json={"ids": [out["action_id"]]})
    assert r.status_code == 200, r.text
    db_session.expire_all()
    item = db_session.get(InventoryItem, item_id)
    assert item is None or getattr(item, "deleted_at", None) is not None


def test_change_is_refused_without_the_users_permission(client, login, org, db_session):
    from app.domains.access.models import AccessLevel

    item_id = _item(login)
    level = db_session.query(AccessLevel).filter_by(name="Member").one()
    level.privileges = json.dumps(sorted(set(json.loads(level.privileges)) | {"ai.use"}))
    db_session.commit()
    out = _call(client, _token(login, "comp_member"), "portal_change", method="DELETE",
                path=f"/api/inventory/{item_id}", summary="Delete the Arduino")
    assert "proposed" not in out and out["status"] in (403, 404), out  # the page hides items it may not touch


def test_chained_changes_fill_in_ids_from_earlier_actions(client, login, org, db_session):
    admin = login("admin")
    root = ensure_position(admin)
    headers = _token(login)
    ev = _call(client, headers, "portal_change", method="POST", path="/api/events",
               body={"name": "Chained Cup", "role_root_position_id": root}, summary="Create Chained Cup")
    assert ev["proposed"], ev
    cat = _call(client, headers, "portal_change", method="POST",
                path=f"/api/events/{{{{#{ev['action_id']}.id}}}}/categories",
                body={"name": "Open"}, summary="Add an Open category to Chained Cup")
    assert cat["proposed"], cat
    r = admin.post("/api/ai/actions/confirm", json={"ids": [ev["action_id"], cat["action_id"]]})
    assert r.status_code == 200, r.text
    event = next(e for e in admin.get("/api/events").json() if e["name"] == "Chained Cup")
    detail = admin.get(f"/api/events/{event['id']}").json()
    assert [c["name"] for c in detail["categories"]] == ["Open"]


def test_routes_outside_the_catalogue_are_refused(client, login, org):
    headers = _token(login)
    out = _call(client, headers, "portal_change", method="POST", path="/api/ai/actions/confirm",
                body={"ids": [1]}, summary="Confirm everything")
    assert "proposed" not in out and out["status"] == 400
    out = _call(client, headers, "portal_read", path="https://example.com/api/users")
    assert out["status"] == 400


def test_portal_read_returns_page_data_as_the_user(client, login, org):
    _item(login, "Servo", 3)
    data = _call(client, _token(login), "portal_read", path="/api/inventory")
    names = [i["name"] for i in (data if isinstance(data, list) else data.get("items", []))]
    assert "Servo" in names


def test_an_outside_request_cannot_borrow_a_session(client, org):
    client.cookies.clear()
    r = client.get("/api/auth/me", headers={"x-ai-run": "guessed-key"})
    assert r.status_code == 401
