"""Free-tier model chain: the tool loop runs through the portal's own token
routes, a rate-limited or broken model hands over to the next one mid-turn,
and every schema/message is cut down to what all providers accept."""

import json

import httpx
import pytest

from app.core.config import settings
from app.domains.ai import router as ai_router
from app.domains.ai.providers import chain
from app.domains.ai.tools import catalog
from app.main import app

LINKS = "gemini:lite-a,gemini:lite-b,groq:oss"


@pytest.fixture(autouse=True)
def _chain_settings(monkeypatch):
    monkeypatch.setattr(settings, "ai_provider", "chain")
    monkeypatch.setattr(settings, "ai_chain", LINKS)
    monkeypatch.setattr(settings, "gemini_api_key", "g-key")
    monkeypatch.setattr(settings, "groq_api_key", "q-key")
    chain.reset_cooldowns()
    yield
    chain.reset_cooldowns()
    ai_router.set_provider(None)


def _reply(content=None, tool_calls=None, **extra):
    msg = {"role": "assistant", "content": content, **extra}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return httpx.Response(200, json={"choices": [{"message": msg}]})


def _call(call_id, tool, **args):
    return {"id": call_id, "type": "function", "function": {"name": tool, "arguments": json.dumps(args)}}


class Models:
    """Fake model APIs: a queue of responses per model id, and every request seen."""

    def __init__(self, script: dict[str, list]):
        self.script, self.seen = script, []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.seen.append((request.url.host, body))
        queue = self.script.get(body["model"]) or [httpx.Response(503, text="no script")]
        return queue.pop(0) if len(queue) > 1 else queue[0]


def _chat(login, models: Models, text="who is the admin?"):
    ai_router.set_provider(chain.ChainProvider(
        transport=httpx.MockTransport(models), portal_transport=httpx.ASGITransport(app=app)))
    admin = login("admin")
    conv = admin.post("/api/ai/conversations", json={"mode": "assistant"}).json()
    r = admin.post(f"/api/ai/conversations/{conv['id']}/messages", json={"text": text})
    assert r.status_code == 200, r.text
    events = [json.loads(line[6:]) for line in r.text.splitlines() if line.startswith("data: ")]
    return admin, conv["id"], events


def test_falls_back_mid_turn_and_runs_tools_as_the_user(client, login, org):
    models = Models({
        "lite-a": [httpx.Response(429, text='{"error": {"details": [{"quotaId": "GenerateRequestsPerDayPerProject"}]}}')],
        "lite-b": [
            _reply(None, [_call("c1", "find_person", name="admin") | {"extra_content": {"google": {"thought_signature": "sig1"}}}]),
            httpx.Response(503, text="overloaded"),
        ],
        "oss": [_reply("The admin is listed above.")],
    })
    admin, conv_id, events = _chat(login, models)

    types = [e["type"] for e in events]
    assert "error" not in types, events
    assert [e["model"] for e in events if e["type"] == "model"] == ["gemini:lite-b", "groq:oss"]
    result = next(e for e in events if e["type"] == "tool_result")["result"]
    assert result["matches"], result  # the tool really ran, through the token route
    assert events[-2] == {"type": "text", "text": "The admin is listed above."}

    # lite-a is out for the day (until midnight Pacific), lite-b only briefly
    status = {s["link"]: s for s in admin.get("/api/ai/status").json()["chain"]}
    assert not status["gemini:lite-a"]["ready"] and status["gemini:lite-a"]["retry_in_s"] > 60
    assert not status["gemini:lite-b"]["ready"] and status["gemini:lite-b"]["retry_in_s"] <= 30

    # Groq got the Gemini-made call stripped of Gemini-only fields
    groq_body = next(body for host, body in models.seen if host == "api.groq.com")
    call_msg = next(m for m in groq_body["messages"] if m.get("tool_calls"))
    assert "extra_content" not in call_msg["tool_calls"][0]
    assert groq_body["messages"][-1]["role"] == "tool"

    saved = admin.get(f"/api/ai/conversations/{conv_id}").json()["messages"]
    assert saved[-1]["role"] == "assistant" and saved[-1]["tools"][0]["name"] == "find_person"


def test_every_link_down_ends_with_a_clear_error(client, login, org):
    models = Models({m: [httpx.Response(429, headers={"retry-after": "120"}, text="slow down")]
                     for m in ("lite-a", "lite-b", "oss")})
    _, _, events = _chat(login, models)
    err = next(e for e in events if e["type"] == "error")
    assert "busy or out of quota" in err["message"] and "2 min" in err["message"]
    assert len(models.seen) == 3
    # a second message doesn't hammer links still cooling down
    _chat(login, models)
    assert len(models.seen) == 3


def test_history_replays_earlier_turns_as_plain_messages(client, login, org):
    models = Models({"lite-a": [_reply("first answer"), _reply("second answer")]})
    admin, conv_id, _ = _chat(login, models, text="first question")
    r = admin.post(f"/api/ai/conversations/{conv_id}/messages", json={"text": "second question"})
    assert r.status_code == 200
    sent = models.seen[-1][1]["messages"]
    assert [(m["role"], m["content"]) for m in sent[1:]] == [
        ("user", "first question"), ("assistant", "first answer"), ("user", "second question")]


def test_links_without_a_key_are_skipped(client, login, org, monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "")
    assert [link.label for link in chain.configured_links()] == ["groq:oss"]
    monkeypatch.setattr(settings, "groq_api_key", "")
    admin = login("admin")
    assert admin.get("/api/ai/status").json()["available"] is False
    conv = admin.post("/api/ai/conversations", json={}).json()
    assert admin.post(f"/api/ai/conversations/{conv['id']}/messages", json={"text": "hi"}).status_code == 503


def test_tool_schemas_are_flattened_for_strict_providers():
    specs = json.dumps(chain.tool_specs(catalog()))
    for banned in ('"$ref"', '"$defs"', '"title": "', '"additionalProperties"', '{"type": "null"}'):
        assert banned not in specs, banned
    doc = next(s for s in chain.tool_specs(catalog()) if s["function"]["name"] == "make_document")
    block = doc["function"]["parameters"]["properties"]["blocks"]["items"]
    assert "for_each" in block["properties"]  # nested model inlined, not referenced


def test_gemini_gets_a_placeholder_signature_for_foreign_calls():
    msgs = [{"role": "assistant", "content": None, "tool_calls": [_call("x", "find_person", name="a")]}]
    gem = chain.for_provider(msgs, "gemini")[0]
    assert gem["tool_calls"][0]["extra_content"]["google"]["thought_signature"] == chain.DUMMY_SIGNATURE
    assert gem["content"] == ""
    assert "extra_content" not in chain.for_provider(msgs, "groq")[0]["tool_calls"][0]
