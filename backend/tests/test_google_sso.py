"""Google SSO: config flag, unconfigured redirects, state validation, the
domain allowlist, and — critically — that accounts are never auto-created and
an existing password account must be linked explicitly, not silently matched
by email."""

import httpx
import pytest


def test_config_reports_google_disabled_by_default(client, org):
    r = client.get("/api/auth/config")
    assert r.status_code == 200
    assert r.json() == {"google_enabled": False}


def test_google_login_redirects_with_error_when_unconfigured(client, org):
    r = client.get("/api/auth/google/login", follow_redirects=False)
    assert r.status_code == 307
    assert r.headers["location"].endswith("/login?error=google_not_configured")


def test_google_callback_rejects_when_unconfigured(client, org):
    r = client.get("/api/auth/google/callback?code=x&state=y", follow_redirects=False)
    assert r.status_code == 307
    assert "error=google_not_configured" in r.headers["location"]


def test_google_callback_state_mismatch(client, org, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "google_client_id", "id")
    monkeypatch.setattr(settings, "google_client_secret", "secret")

    # no state cookie at all
    r = client.get("/api/auth/google/callback?code=x&state=y", follow_redirects=False)
    assert "error=google_state_mismatch" in r.headers["location"]

    # provider-side error / missing code
    r = client.get("/api/auth/google/callback?error=access_denied", follow_redirects=False)
    assert "error=google_denied" in r.headers["location"]


@pytest.fixture()
def google_enabled(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "google_client_id", "id")
    monkeypatch.setattr(settings, "google_client_secret", "secret")


def _mock_google(monkeypatch, email: str, *, verified: bool = True, hd: str | None = None):
    """Stub the two outbound httpx calls the callback makes."""

    class FakeResp:
        def __init__(self, payload, status_code=200):
            self._payload = payload
            self.status_code = status_code

        def json(self):
            return self._payload

    def fake_post(url, **kw):
        return FakeResp({"access_token": "fake-token"})

    def fake_get(url, **kw):
        info = {"email": email, "email_verified": verified}
        if hd:
            info["hd"] = hd
        return FakeResp(info)

    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setattr(httpx, "get", fake_get)


def _do_callback(client, cookies=None):
    """Complete a callback with a valid state (skip the state-cookie dance by
    hitting the endpoint the same way the browser would after /google/login)."""
    r = client.get("/api/auth/google/login", follow_redirects=False)
    state_cookie = r.cookies.get("g_oauth_state")
    all_cookies = {"g_oauth_state": state_cookie, **(cookies or {})}
    # the redirect URL embeds the same state value
    import re

    m = re.search(r"state=([^&]+)", r.headers["location"])
    state = m.group(1)
    return client.get(
        f"/api/auth/google/callback?code=abc&state={state}",
        cookies=all_cookies,
        follow_redirects=False,
    )


def test_unknown_email_is_never_auto_provisioned(client, org, google_enabled, monkeypatch):
    _mock_google(monkeypatch, "nobody@t.local")
    r = _do_callback(client)
    assert "error=no_account" in r.headers["location"]

    # and no account was silently created
    login = client.post("/api/auth/login", json={"email": "nobody@t.local", "password": "x"})
    assert login.status_code == 401


def test_email_unverified_rejected(client, org, google_enabled, monkeypatch):
    _mock_google(monkeypatch, org["cto"].email, verified=False)
    r = _do_callback(client)
    assert "error=google_email_unverified" in r.headers["location"]


def test_domain_allowlist_blocks_disallowed_domain(client, org, google_enabled, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "google_allowed_domains", "mindtechrobotics.org")
    _mock_google(monkeypatch, org["cto"].email, hd="evilcorp.com")
    r = _do_callback(client)
    assert "error=google_domain_not_allowed" in r.headers["location"]


def test_domain_allowlist_permits_listed_domain(client, org, google_enabled, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "google_allowed_domains", "t.local")
    # existing account, but not yet linked — expect link_required, NOT domain rejection
    _mock_google(monkeypatch, org["cto"].email, hd="t.local")
    r = _do_callback(client)
    assert "error=link_required" in r.headers["location"]


def test_existing_password_account_requires_explicit_link_not_silent_match(
    client, org, google_enabled, monkeypatch
):
    _mock_google(monkeypatch, org["cto"].email)
    r = _do_callback(client)
    assert "error=link_required" in r.headers["location"]
    # crucially: no session was issued
    assert "portal_session" not in r.cookies


def test_explicit_link_then_google_signin_works(client, org, google_enabled, monkeypatch):
    # 1) prove ownership with a normal password login
    login = client.post("/api/auth/login", json={"email": org["cto"].email, "password": "testpass123"})
    assert login.status_code == 200
    session_cookie = login.cookies.get("portal_session")

    # 2) hit the Google round-trip WITH that session present -> explicit link
    _mock_google(monkeypatch, org["cto"].email)
    r = _do_callback(client, cookies={"portal_session": session_cookie})
    assert "linked=true" in r.headers["location"]

    # 3) now a fresh Google sign-in (no password session) succeeds directly —
    # clear the client's cookie jar first, since it still holds the session
    # from step 1 otherwise (which would just re-confirm the link, not test
    # the plain sign-in path)
    client.cookies.clear()
    r2 = _do_callback(client)
    assert r2.headers["location"].endswith("/tasks")
    assert "portal_session" in r2.cookies


def test_link_rejects_mismatched_email(client, org, google_enabled, monkeypatch):
    login = client.post("/api/auth/login", json={"email": org["cto"].email, "password": "testpass123"})
    session_cookie = login.cookies.get("portal_session")

    _mock_google(monkeypatch, org["ceo"].email)  # different account's email
    r = _do_callback(client, cookies={"portal_session": session_cookie})
    assert "error=google_account_mismatch" in r.headers["location"]


def test_deactivated_account_blocked_even_when_linked(client, org, google_enabled, monkeypatch, db_session):
    from app.domains.users.models import User

    login = client.post("/api/auth/login", json={"email": org["cto"].email, "password": "testpass123"})
    session_cookie = login.cookies.get("portal_session")
    _mock_google(monkeypatch, org["cto"].email)
    _do_callback(client, cookies={"portal_session": session_cookie})  # link it

    user = db_session.get(User, org["cto"].id)
    user.is_active = False
    db_session.commit()

    r = _do_callback(client)
    assert "error=account_disabled" in r.headers["location"]
