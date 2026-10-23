"""Forgot-password flow: emailed one-hour link, no account enumeration,
single use, and a reset signs every session out."""

from datetime import datetime, timedelta, timezone

import pytest

from app.domains.auth import router as auth_router
from app.domains.auth.models import AuthSession, PasswordResetToken
from tests.conftest import PASSWORD


@pytest.fixture()
def outbox(monkeypatch):
    sent = []

    def fake_send(to, subject, text, html=None, **kw):
        sent.append({"to": to, "subject": subject, "text": text, "html": html})
        return True

    monkeypatch.setattr(auth_router, "send_email", fake_send)
    return sent


def _token_from(mail) -> str:
    return mail["text"].split("reset-password?token=", 1)[1].split()[0]


def test_forgot_sends_link_and_reset_works(client, org, outbox, db_session):
    user = org["cto"]
    old = client.post("/api/auth/login", json={"email": user.email, "password": PASSWORD})
    assert old.status_code == 200

    r = client.post("/api/auth/forgot-password", json={"email": user.email.upper()})
    assert r.status_code == 204
    assert len(outbox) == 1 and outbox[0]["to"] == user.email
    token = _token_from(outbox[0])
    # only the hash is stored
    assert db_session.get(PasswordResetToken, token) is None

    r = client.post(
        "/api/auth/reset-password", json={"token": token, "new_password": "brandnew123"}
    )
    assert r.status_code == 204
    assert db_session.query(AuthSession).filter_by(user_id=user.id).count() == 0
    assert client.get("/api/auth/me", cookies=dict(old.cookies)).status_code == 401

    bad = client.post("/api/auth/login", json={"email": user.email, "password": PASSWORD})
    assert bad.status_code == 401
    good = client.post("/api/auth/login", json={"email": user.email, "password": "brandnew123"})
    assert good.status_code == 200

    # single use
    again = client.post(
        "/api/auth/reset-password", json={"token": token, "new_password": "another123"}
    )
    assert again.status_code == 400


def test_unknown_email_is_silent(client, org, outbox):
    r = client.post("/api/auth/forgot-password", json={"email": "nobody@gmail.com"})
    assert r.status_code == 204
    assert outbox == []


def test_cooldown_limits_emails(client, org, outbox):
    email = org["cto"].email
    for _ in range(3):
        assert client.post("/api/auth/forgot-password", json={"email": email}).status_code == 204
    assert len(outbox) == 1


def test_expired_and_bogus_tokens_rejected(client, org, outbox, db_session):
    client.post("/api/auth/forgot-password", json={"email": org["cto"].email})
    token = _token_from(outbox[0])
    row = db_session.query(PasswordResetToken).one()
    row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db_session.commit()
    r = client.post(
        "/api/auth/reset-password", json={"token": token, "new_password": "brandnew123"}
    )
    assert r.status_code == 400
    r = client.post(
        "/api/auth/reset-password", json={"token": "nope", "new_password": "brandnew123"}
    )
    assert r.status_code == 400


def test_new_password_validated(client, org, outbox):
    client.post("/api/auth/forgot-password", json={"email": org["cto"].email})
    r = client.post(
        "/api/auth/reset-password", json={"token": _token_from(outbox[0]), "new_password": "short"}
    )
    assert r.status_code == 422
