"""The hosted MCP endpoint outside AI agents connect to, and the OAuth sign-in
that gives them a lasting token whose writes run directly."""

import base64
import hashlib
from urllib.parse import parse_qs, urlsplit

import pytest

from app.core.config import settings
from app.domains.ai import embeddings, router as ai_router
from app.domains.inventory.models import InventoryItem

HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
REDIRECT = "http://127.0.0.1:33418/callback"
VERIFIER = "v" * 50
CHALLENGE = base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).rstrip(b"=").decode()


@pytest.fixture(autouse=True)
def _offline_embedder():
    embeddings.set_embedder(embeddings.HashEmbedder())
    yield
    embeddings.set_embedder(None)
    ai_router.set_provider(None)


def _rpc(client, token, method, params=None, rid=1):
    return client.post("/api/ai/mcp", headers={**HEADERS, "Authorization": f"Bearer {token}"},
                       json={"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}})


def _register(client, name="Claude Code", redirect=REDIRECT):
    r = client.post("/api/oauth/register", json={"client_name": name, "redirect_uris": [redirect]})
    assert r.status_code == 201, r.text
    return r.json()["client_id"]


def _sign_in(client, login, who="admin", name="Claude Code") -> str:
    """The whole flow an agent drives: register, authorize, consent, token."""
    client_id = _register(client, name)
    # an agent may come back on any loopback port (RFC 8252)
    redirect = "http://127.0.0.1:51234/callback"
    auth = client.get("/api/oauth/authorize", follow_redirects=False, params={
        "response_type": "code", "client_id": client_id, "redirect_uri": redirect,
        "code_challenge": CHALLENGE, "code_challenge_method": "S256", "state": "xyz"})
    assert auth.status_code in (302, 307), auth.text
    assert auth.headers["location"].startswith(f"{settings.frontend_url}/oauth/consent?")
    info = login(who).get(f"/api/oauth/clients/{client_id}", params={"redirect_uri": redirect})
    assert info.json()["name"] == name
    decision = login(who).post("/api/oauth/decision", json={
        "client_id": client_id, "redirect_uri": redirect, "code_challenge": CHALLENGE,
        "state": "xyz", "approve": True})
    assert decision.status_code == 200, decision.text
    back = urlsplit(decision.json()["redirect"])
    query = parse_qs(back.query)
    assert back.netloc == "127.0.0.1:51234" and query["state"] == ["xyz"]
    tok = client.post("/api/oauth/token", data={
        "grant_type": "authorization_code", "code": query["code"][0], "redirect_uri": redirect,
        "client_id": client_id, "code_verifier": VERIFIER})
    assert tok.status_code == 200, tok.text
    assert tok.json()["token_type"] == "Bearer" and "expires_in" not in tok.json()
    return tok.json()["access_token"]


def test_discovery_points_agents_at_the_sign_in(client):
    r = _rpc(client, "", "tools/list")
    assert r.status_code == 401
    assert "resource_metadata=" in r.headers["WWW-Authenticate"]
    pr = client.get("/.well-known/oauth-protected-resource/api/ai/mcp").json()
    assert pr["resource"].endswith("/api/ai/mcp")
    meta = client.get("/.well-known/oauth-authorization-server").json()
    assert meta["issuer"] == pr["authorization_servers"][0]
    assert meta["code_challenge_methods_supported"] == ["S256"]
    assert meta["registration_endpoint"].endswith("/api/oauth/register")


def test_signed_in_agent_reads_and_writes_directly(client, login, db_session):
    token = _sign_in(client, login)
    init = _rpc(client, token, "initialize", {
        "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}})
    assert init.status_code == 200, init.text
    assert "run immediately" in init.json()["result"]["instructions"]

    tools = {t["name"]: t for t in _rpc(client, token, "tools/list", rid=2).json()["result"]["tools"]}
    assert "list_pending_actions" not in tools
    assert "PROPOSE" not in tools["portal_change"]["description"]

    call = _rpc(client, token, "tools/call", {"name": "portal_change", "arguments": {
        "method": "POST", "path": "/api/inventory", "body": {"name": "Hosted MCP part", "quantity": 3},
        "summary": "Add 3 Hosted MCP parts to inventory"}}, rid=3)
    assert call.status_code == 200, call.text
    result = call.json()["result"]
    assert result["isError"] is False, result
    item = db_session.query(InventoryItem).filter_by(name="Hosted MCP part").one()
    assert item.quantity == 3  # written at once, no confirmation step

    bad = _rpc(client, token, "tools/call", {"name": "portal_change", "arguments": {
        "method": "DELETE", "path": "/api/inventory/999999", "summary": "Delete a missing item"}}, rid=4)
    assert bad.json()["result"]["isError"] is True


def test_only_people_with_ai_use_can_connect_an_agent(client, login):
    client_id = _register(client)
    r = login("comp_member").post("/api/oauth/decision", json={
        "client_id": client_id, "redirect_uri": REDIRECT, "code_challenge": CHALLENGE, "approve": True})
    assert r.status_code == 403


def test_connections_last_until_disconnected(client, login):
    first = _sign_in(client, login, name="Claude Code")
    second = _sign_in(client, login, name="Codex")
    assert _rpc(client, first, "tools/list").status_code == 200

    conns = login("admin").get("/api/ai/connections").json()
    assert [c["agent"] for c in conns] == ["Codex", "Claude Code"]
    claude = next(c for c in conns if c["agent"] == "Claude Code")
    assert claude["last_used_at"] is not None

    assert login("admin").delete(f"/api/ai/connections/{claude['id']}").status_code == 204
    assert _rpc(client, first, "tools/list").status_code == 401
    assert _rpc(client, second, "tools/list").status_code == 200
    assert login("comp_member").delete(f"/api/ai/connections/{conns[0]['id']}").status_code == 404


def test_code_is_single_use_and_needs_the_verifier(client, login):
    client_id = _register(client)
    code_url = login("admin").post("/api/oauth/decision", json={
        "client_id": client_id, "redirect_uri": REDIRECT, "code_challenge": CHALLENGE, "approve": True}).json()["redirect"]
    code = parse_qs(urlsplit(code_url).query)["code"][0]
    form = {"grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT, "client_id": client_id}
    assert client.post("/api/oauth/token", data={**form, "code_verifier": "w" * 50}).json()["error"] == "invalid_grant"
    assert client.post("/api/oauth/token", data={**form, "code_verifier": VERIFIER}).status_code == 200
    assert client.post("/api/oauth/token", data={**form, "code_verifier": VERIFIER}).status_code == 400


def test_denied_consent_and_bad_redirects(client, login):
    client_id = _register(client)
    denied = login("admin").post("/api/oauth/decision", json={
        "client_id": client_id, "redirect_uri": REDIRECT, "code_challenge": CHALLENGE, "approve": False})
    assert "error=access_denied" in denied.json()["redirect"]
    # a redirect the agent never registered is refused, never followed
    other = login("admin").post("/api/oauth/decision", json={
        "client_id": client_id, "redirect_uri": "https://evil.example/cb", "code_challenge": CHALLENGE, "approve": True})
    assert other.status_code == 400
    r = client.post("/api/oauth/register", json={"redirect_uris": ["http://evil.example/cb"]})
    assert r.status_code == 400
    assert client.post("/api/oauth/register", json={"redirect_uris": ["javascript:alert(1)"]}).status_code == 400


def test_portal_chat_tokens_still_only_propose(client, login):
    r = login("admin").post("/api/ai/connect")
    token = r.json()["token"]
    call = client.post("/api/ai/tools/portal_change", headers={"Authorization": f"Bearer {token}"}, json={
        "arguments": {"method": "POST", "path": "/api/inventory", "body": {"name": "Proposed part", "quantity": 1},
                      "summary": "Add a proposed part"}})
    assert call.json()["proposed"] is True
