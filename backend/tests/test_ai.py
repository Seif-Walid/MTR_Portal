"""AI assistant: tools run as the user, writes wait for confirmation, confirm
is all-or-nothing, tokens are scoped, search heals its index."""

import json

import pytest

from app.domains.ai import embeddings, search as semantic
from app.domains.ai import router as ai_router
from app.domains.ai.models import AiEmbedding
from app.domains.ai.providers.claude_code import build_command, parse_line
from app.domains.ai.providers.fake import FakeProvider
from app.domains.inventory.models import InventoryAllocation

from tests.conftest import ensure_position, setup_role_templates


@pytest.fixture(autouse=True)
def _hash_embedder():
    embeddings.set_embedder(embeddings.HashEmbedder(
        synonyms={"buck": "stepdown", "step": "stepdown", "down": "stepdown"}))
    yield
    embeddings.set_embedder(None)
    ai_router.set_provider(None)


def _token(login, who="admin") -> dict:
    r = login(who).post("/api/ai/connect")
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _call(client, headers, tool, **arguments):
    r = client.post(f"/api/ai/tools/{tool}", json={"arguments": arguments}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _item(login, name, quantity, who="admin"):
    r = login(who).post("/api/inventory", json={"name": name, "quantity": quantity})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _event_with_team(login):
    admin = login("admin")
    root = ensure_position(admin)
    ev = admin.post("/api/events", json={"name": "Comp C", "role_root_position_id": root}).json()
    cat = admin.post(f"/api/events/{ev['id']}/categories", json={"name": "Open"}).json()
    team = admin.post(f"/api/events/categories/{cat['id']}/teams",
                      json={"name": "Team A", "role_root_position_id": root}).json()
    return ev["id"], team["id"]


def test_ai_use_privilege_gates_assistant(client, login, org):
    assert login("comp_member").post("/api/ai/connect").status_code == 403
    assert login("cto").post("/api/ai/connect").status_code == 403  # test Lead level lacks ai.use
    assert login("admin").post("/api/ai/connect").status_code == 200


def test_token_only_opens_tool_routes(client, login, org):
    headers = _token(login)
    assert client.get("/api/ai/tools", headers=headers).status_code == 200
    assert client.get("/api/ai/tools", headers={"Authorization": "Bearer nope"}).status_code == 401
    # the AI token is not a session: normal API routes stay closed
    client.cookies.clear()
    assert client.get("/api/inventory", headers=headers).status_code == 401


def test_write_tool_only_proposes_then_confirm_allocates_to_team(client, login, org, db_session):
    item_id = _item(login, "L298N motor driver", 10)
    event_id, team_id = _event_with_team(login)
    headers = _token(login)
    out = _call(client, headers, "allocate_inventory",
                lines=[{"item_id": item_id, "quantity": 4}], team_id=team_id)
    assert out["proposed"] is True, out
    assert "4× L298N motor driver" in out["summary"] and "Team A" in out["summary"]
    assert db_session.query(InventoryAllocation).count() == 0  # nothing happened yet

    pending = login("admin").get("/api/ai/actions").json()
    assert [a["id"] for a in pending] == [out["action_id"]]
    r = login("admin").post("/api/ai/actions/confirm", json={"ids": [out["action_id"]]})
    assert r.status_code == 200, r.text
    alloc = db_session.query(InventoryAllocation).one()
    assert (alloc.quantity, alloc.event_team_id, alloc.event_id) == (4, team_id, event_id)
    item = login("admin").get(f"/api/inventory/{item_id}").json()
    assert item["free"] == 6
    assert item["allocations"][0]["team_name"] == "Team A"
    # can't confirm twice
    assert login("admin").post("/api/ai/actions/confirm", json={"ids": [out["action_id"]]}).status_code == 409


def test_dry_run_rejects_over_allocation_across_pending_chain(client, login, org):
    item_id = _item(login, "Buck converter", 5)
    headers = _token(login)
    first = _call(client, headers, "allocate_inventory", lines=[{"item_id": item_id, "quantity": 3}])
    assert first["proposed"]
    second = _call(client, headers, "allocate_inventory", lines=[{"item_id": item_id, "quantity": 3}])
    assert "error" in second and "proposed" not in second  # 3 + 3 > 5


def test_confirm_is_all_or_nothing(client, login, org, db_session):
    item_id = _item(login, "Servo", 5)
    headers = _token(login)
    a = _call(client, headers, "allocate_inventory", lines=[{"item_id": item_id, "quantity": 2}])
    b = _call(client, headers, "allocate_inventory", lines=[{"item_id": item_id, "quantity": 3}])
    # someone else takes stock meanwhile, so b no longer fits
    login("admin").post(f"/api/inventory/{item_id}/allocations", json={"quantity": 1, "purpose": "training"})
    r = login("admin").post("/api/ai/actions/confirm", json={"ids": [a["action_id"], b["action_id"]]})
    assert r.status_code == 400 and f"#{b['action_id']}" in r.json()["detail"]
    assert db_session.query(InventoryAllocation).count() == 1  # only the manual one
    assert {x["id"] for x in login("admin").get("/api/ai/actions").json()} == {a["action_id"], b["action_id"]}


def test_actions_run_with_the_users_own_permissions(client, login, org, db_session):
    from app.domains.access.models import AccessLevel

    item_id = _item(login, "Arduino", 5)
    # give the test "Member" level ai.use but not inventory.edit
    level = db_session.query(AccessLevel).filter_by(name="Member").one()
    level.privileges = json.dumps(sorted(set(json.loads(level.privileges)) | {"ai.use"}))
    db_session.commit()
    headers = _token(login, "comp_member")
    out = _call(client, headers, "allocate_inventory", lines=[{"item_id": item_id, "quantity": 1}])
    assert "proposed" not in out and out.get("status") in (403, 404)


def test_create_event_with_manager_and_chained_team(client, login, org, db_session):
    admin = login("admin")
    setup_role_templates(admin, pm=True)
    # the first role seat ever needs a place in the org chart (asked once)
    admin.post("/api/events", json={"name": "Seed", "role_root_position_id": ensure_position(admin)})
    headers = _token(login)
    person = _call(client, headers, "find_person", name="pmm")["matches"][0]
    assert person["user_id"] == org["pm"].id
    ev = _call(client, headers, "create_event", name="MRC", kind="competition", manager_user_id=person["user_id"])
    assert ev.get("proposed"), ev
    team = _call(client, headers, "create_team", name="ROV A", event_from_action=ev["action_id"])
    assert team["proposed"], team
    r = admin.post("/api/ai/actions/confirm", json={"ids": [ev["action_id"], team["action_id"]]})
    assert r.status_code == 200, r.text
    done = {d["action_id"]: d["result"] for d in r.json()["done"]}
    event_id = done[ev["action_id"]]["event_id"]
    assert done[team["action_id"]]["event_id"] == event_id
    detail = _call(client, headers, "get_event", event_id=event_id)
    assert any(org["pm"].full_name in role["occupants"] for role in detail["roles"])


def test_confirmed_tasks_fan_out(client, login, org):
    headers = _token(login)
    out = _call(client, headers, "create_tasks", title="Design frame",
                assignee_ids=[org["student"].id, org["comp_member"].id])
    assert out["proposed"], out
    r = login("admin").post("/api/ai/actions/confirm", json={"ids": [out["action_id"]]})
    assert len(r.json()["done"][0]["result"]["task_ids"]) == 2


def test_html_escaped_arguments_are_stored_plain(client, login, org):
    headers = _token(login)
    out = _call(client, headers, "create_tasks", title="Electronics &amp; Power", assignee_ids=[org["student"].id])
    assert "Electronics & Power" in out["summary"] and "&amp;" not in out["summary"]


def test_semantic_search_finds_other_names_and_heals_index(client, login, org, db_session):
    buck = _item(login, "LM2596 step-down converter", 7)
    _item(login, "Ultrasonic sensor", 3)
    hits = login("admin").get("/api/ai/search", params={"q": "buck driver", "types": "inventory"}).json()
    assert hits[0]["id"] == buck
    before = {e.entity_id: e.text_hash for e in db_session.query(AiEmbedding)}
    login("admin").patch(f"/api/inventory/{buck}", json={"notes": "5A module"})
    login("admin").get("/api/ai/search", params={"q": "sensor", "types": "inventory"})
    after = {e.entity_id: e.text_hash for e in db_session.query(AiEmbedding)}
    changed = {i for i in after if after[i] != before.get(i)}
    assert changed == {buck}


def test_search_respects_view_privileges(client, login, org):
    _item(login, "Secret part", 1)
    assert login("comp_member").get("/api/ai/search", params={"q": "secret", "types": "inventory"}).json() == []


def test_chat_streams_and_saves_turn(client, login, org):
    fake = FakeProvider([{"type": "text", "text": "Hello "}, {"type": "text", "text": "there"}])
    ai_router.set_provider(fake)
    admin = login("admin")
    conv = admin.post("/api/ai/conversations", json={"mode": "assistant"}).json()
    r = admin.post(f"/api/ai/conversations/{conv['id']}/messages", json={"text": "hi"})
    assert r.status_code == 200
    events = [json.loads(line[6:]) for line in r.text.splitlines() if line.startswith("data: ")]
    assert [e["type"] for e in events] == ["text", "text", "done"]
    detail = admin.get(f"/api/ai/conversations/{conv['id']}").json()
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]
    assert detail["messages"][1]["text"] == "Hello there"
    assert fake.calls[0]["token"].startswith("mtrai_")


def test_claude_code_provider_refused_in_prod(client, login, org, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "ai_provider", "claude_code")
    monkeypatch.setattr(settings, "cookie_secure", True)
    admin = login("admin")
    conv = admin.post("/api/ai/conversations", json={}).json()
    r = admin.post(f"/api/ai/conversations/{conv['id']}/messages", json={"text": "hi"})
    assert r.status_code == 503


def test_claude_code_command_is_locked_down():
    cmd = build_command(text="x", mode="assistant", token="t", session_id="s1", system="sys")
    assert cmd[cmd.index("--tools") + 1] == ""  # no built-in tools at all
    assert "--strict-mcp-config" in cmd and cmd[cmd.index("--resume") + 1] == "s1"
    planner = build_command(text="x", mode="planner", token="t", session_id=None, system="sys")
    assert planner[planner.index("--tools") + 1] == "WebSearch,WebFetch"
    names: dict = {}
    assert parse_line({"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": "u1", "name": "mcp__portal__find_person", "input": {"name": "x"}}]}}, names) \
        == [{"type": "tool", "name": "find_person", "input": {"name": "x"}}]
    assert parse_line({"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": "u1", "content": [{"type": "text", "text": "{\"a\": 1}"}]}]}}, names) \
        == [{"type": "tool_result", "name": "find_person", "result": {"a": 1}}]


def test_query_data_is_read_only_and_permission_filtered(client, login, org, db_session):
    from app.domains.access.models import AccessLevel

    _item(login, "LM2596 step-down converter", 7)
    headers = _token(login)
    tables = {t["table"]: t["columns"] for t in _call(client, headers, "data_schema")["tables"]}
    assert "inventory_items" in tables and "ai_tokens" not in tables and "auth_sessions" not in tables
    assert not any("hash" in c or "password" in c for cols in tables.values() for c in cols)
    out = _call(client, headers, "query_data", sql="SELECT name, quantity FROM inventory_items")
    assert out["rows"] == [["LM2596 step-down converter", 7]]
    assert "error" in _call(client, headers, "query_data", sql="DELETE FROM inventory_items")
    assert "error" in _call(client, headers, "query_data", sql="SELECT 1; DROP TABLE x")
    # a Member with ai.use sees neither inventory nor the people table
    level = db_session.query(AccessLevel).filter_by(name="Member").one()
    level.privileges = json.dumps(sorted(set(json.loads(level.privileges)) | {"ai.use"}))
    db_session.commit()
    member = _token(login, "comp_member")
    assert "no such table" in _call(client, member, "query_data", sql="SELECT * FROM inventory_items")["error"]
    names = _call(client, member, "query_data", sql="SELECT full_name FROM user_names WHERE id = %d" % org["pm"].id)
    assert names["rows"] == [[org["pm"].full_name]]  # people.view: names only


def test_make_document_repeats_a_page_per_row_from_sql(client, login, org, db_session):
    import io

    from openpyxl import load_workbook

    from app.domains.events.models import EventTeamMember

    event_id, team_id = _event_with_team(login)
    admin = login("admin")
    assert admin.post(f"/api/events/teams/{team_id}/members", json={"user_id": org["student"].id}).status_code == 201
    db_session.query(EventTeamMember).filter_by(team_id=team_id).one().role = "Pilot"
    db_session.commit()
    headers = _token(login)
    blocks = [{"for_each": "SELECT e.id, e.name, (SELECT count(*) FROM event_teams t JOIN event_categories c ON c.id = t.category_id WHERE c.event_id = e.id) AS teams FROM events e",
               "blocks": [
                   {"text": "# {{name}}\n\nTeams: {{teams}}"},
                   {"table": "SELECT t.name AS team, u.full_name AS member, m.role FROM event_team_members m JOIN event_teams t ON t.id = m.team_id JOIN event_categories c ON c.id = t.category_id JOIN user_names u ON u.id = m.user_id WHERE c.event_id = :id",
                    "heading": "Members of {{name}}"}]}]
    pdf = _call(client, headers, "make_document", format="pdf", filename="Events", title="Events", blocks=blocks)
    assert pdf["filename"] == "Events.pdf" and pdf["built"]["repeats"] >= 1, pdf
    assert admin.get(pdf["download"]).content.startswith(b"%PDF")
    xl = _call(client, headers, "make_document", format="xlsx", filename="Events", title="Events", blocks=blocks)
    wb = load_workbook(io.BytesIO(admin.get(xl["download"]).content))
    sheet = wb["Members of Comp C"]
    assert list(sheet.iter_rows(values_only=True))[1] == ("Team A", org["student"].full_name, "Pilot")
    assert login("ceo").get(xl["download"]).status_code in (403, 404)  # only the maker downloads


def test_event_people_view_merges_members_and_seats(client, login, org, db_session):
    from app.domains.positions.models import Position, PositionOccupant

    event_id, team_id = _event_with_team(login)
    login("admin").post(f"/api/events/teams/{team_id}/members", json={"user_id": org["student"].id})
    seat = Position(title="Team A coach", entity_type="team", entity_id=team_id)
    db_session.add(seat)
    db_session.flush()
    db_session.add(PositionOccupant(position_id=seat.id, user_id=org["pm"].id))
    db_session.commit()
    headers = _token(login)
    out = _call(client, headers, "query_data",
                sql=f"SELECT full_name, role, source FROM event_people WHERE team_id = {team_id} ORDER BY full_name")
    assert [org["pm"].full_name, "Coach", "seat"] in out["rows"]
    assert [org["student"].full_name, None, "member"] in out["rows"]
    kinds = _call(client, headers, "query_data", sql=f"SELECT kind, status FROM event_list WHERE event_id = {event_id}")
    assert kinds["rows"] and kinds["rows"][0][1] == "active"
    empty = _call(client, headers, "query_data",
                  sql=f"SELECT count(DISTINCT team_id), count(DISTINCT user_id) FROM event_people WHERE event_id = {event_id} AND team_id IS NOT NULL")
    assert empty["rows"] == [[1, 2]]


def test_make_document_rejects_mixed_blocks(client, login, org):
    headers = _token(login)
    out = _call(client, headers, "make_document", format="pdf", filename="x", title="x",
                blocks=[{"text": "hi", "table": "SELECT 1"}])
    assert "error" in out and "exactly one" in json.dumps(out)


def test_transcribe_sends_one_clip_to_groq_and_needs_ai_use(client, login, org, monkeypatch):
    from app.core.config import settings
    from app.domains.ai import voice

    clip = {"audio": ("speech.webm", b"\x1aE\xdf\xa3fake", "audio/webm")}
    monkeypatch.setattr(settings, "groq_api_key", "")
    admin = login("admin")
    assert admin.get("/api/ai/status").json()["transcribe"] is False
    assert admin.post("/api/ai/transcribe", files=clip).status_code == 503  # no key yet

    monkeypatch.setattr(settings, "groq_api_key", "gsk_test")
    sent = {}

    class Res:
        status_code = 200
        text = ""

        def json(self):
            return {"text": "  add two servos to the drone team  "}

    def fake_post(url, **kw):
        sent.update(url=url, **kw)
        return Res()

    monkeypatch.setattr(voice.httpx, "post", fake_post)
    assert admin.get("/api/ai/status").json()["transcribe"] is True
    r = admin.post("/api/ai/transcribe", files=clip, data={"language": "ar"})
    assert r.status_code == 200 and r.json() == {"text": "add two servos to the drone team"}
    assert sent["url"] == voice.GROQ_URL
    assert sent["data"]["model"] == settings.ai_transcribe_model and sent["data"]["language"] == "ar"
    assert sent["headers"]["Authorization"] == "Bearer gsk_test"

    Res.status_code = 429
    assert admin.post("/api/ai/transcribe", files=clip).status_code == 429
    assert login("comp_member").post("/api/ai/transcribe", files=clip).status_code == 403
