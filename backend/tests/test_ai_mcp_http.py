"""The hosted MCP endpoint people's own AI agents connect to."""

from app.domains.ai import embeddings, router as ai_router

import pytest

HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


@pytest.fixture(autouse=True)
def _offline_embedder():
    embeddings.set_embedder(embeddings.HashEmbedder())
    yield
    embeddings.set_embedder(None)
    ai_router.set_provider(None)


def _rpc(client, token, method, params=None, rid=1):
    return client.post("/api/ai/mcp", headers={**HEADERS, "Authorization": f"Bearer {token}"},
                       json={"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}})


def _connect(login, agent="Codex"):
    r = login("admin").post("/api/ai/connect", json={"agent": agent})
    assert r.status_code == 200, r.text
    return r.json()


def test_agent_connects_by_url_and_calls_tools(client, login):
    token = _connect(login)["token"]
    init = _rpc(client, token, "initialize", {
        "protocolVersion": "2025-06-18", "capabilities": {},
        "clientInfo": {"name": "test", "version": "1"}})
    assert init.status_code == 200, init.text
    assert init.json()["result"]["serverInfo"]["name"] == "portal"

    tools = _rpc(client, token, "tools/list", rid=2)
    assert tools.status_code == 200, tools.text
    names = {t["name"] for t in tools.json()["result"]["tools"]}
    assert "semantic_search" in names

    call = _rpc(client, token, "tools/call", {"name": "semantic_search", "arguments": {"query": "motor"}}, rid=3)
    assert call.status_code == 200, call.text
    assert call.json()["result"]["isError"] is False


def test_agent_tokens_do_not_expire_and_can_be_revoked(client, login):
    first = _connect(login, "Claude Code")
    second = _connect(login, "Antigravity")
    # a new connection never cuts off the existing ones
    assert _rpc(client, first["token"], "tools/list").status_code == 200

    conns = login("admin").get("/api/ai/connections").json()
    assert [c["agent"] for c in conns] == ["Antigravity", "Claude Code"]
    assert next(c for c in conns if c["id"] == first["connection"]["id"])["last_used_at"] is not None

    assert login("admin").delete(f"/api/ai/connections/{first['connection']['id']}").status_code == 204
    revoked = _rpc(client, first["token"], "tools/list")
    assert revoked.status_code == 401
    assert "WWW-Authenticate" in revoked.headers
    assert _rpc(client, second["token"], "tools/list").status_code == 200


def test_no_or_bad_token_is_refused(client, login):
    assert _rpc(client, "", "tools/list").status_code == 401
    assert _rpc(client, "mtrai_nope", "tools/list").status_code == 401


def test_only_the_owner_can_revoke(client, login):
    conn = _connect(login)["connection"]
    assert login("comp_member").delete(f"/api/ai/connections/{conn['id']}").status_code == 404
