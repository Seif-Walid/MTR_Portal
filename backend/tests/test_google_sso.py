"""Google SSO plumbing (without real Google): config flag, unconfigured
redirects, and state validation. Accounts are never auto-created."""


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
