import httpx
import pytest

from app.core import mail
from app.core.config import settings


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setattr(settings, "mail_backend", "disabled")


def test_disabled_drops_without_network(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("network used")

    monkeypatch.setattr(httpx, "post", boom)
    assert mail.send_email("a@example.com", "hi", "body") is False


def test_cloudflare_payload(monkeypatch):
    monkeypatch.setattr(settings, "mail_backend", "cloudflare")
    monkeypatch.setattr(settings, "cloudflare_account_id", "acct1")
    monkeypatch.setattr(settings, "cloudflare_api_token", "tok")
    seen = {}

    def fake_post(url, headers, json, timeout):
        seen.update(url=url, headers=headers, json=json)
        return httpx.Response(200, json={"success": True, "errors": [], "result": {}})

    monkeypatch.setattr(httpx, "post", fake_post)
    assert mail.send_email("a@example.com", "hi", "body", "<b>body</b>") is True
    assert seen["url"].endswith("/accounts/acct1/email/sending/send")
    assert seen["headers"]["Authorization"] == "Bearer tok"
    assert seen["json"]["from"]["address"] == "portal@mindtechrobotics.com"
    assert seen["json"]["to"] == ["a@example.com"]
    assert seen["json"]["html"] == "<b>body</b>"


def test_cloudflare_failure_is_swallowed(monkeypatch):
    monkeypatch.setattr(settings, "mail_backend", "cloudflare")
    monkeypatch.setattr(
        httpx, "post",
        lambda *a, **k: httpx.Response(400, json={"success": False, "errors": [{"code": 1000}]}),
    )
    assert mail.send_email("a@example.com", "hi", "body") is False


def test_smtp_builds_message(monkeypatch):
    monkeypatch.setattr(settings, "mail_backend", "smtp")
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(settings, "smtp_user", "u")
    monkeypatch.setattr(settings, "smtp_password", "p")
    sent = []

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            assert (host, port) == ("smtp.example.com", 587)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self, context):
            pass

        def login(self, u, p):
            assert (u, p) == ("u", "p")

        def send_message(self, msg):
            sent.append(msg)

    monkeypatch.setattr(mail.smtplib, "SMTP", FakeSMTP)
    assert mail.send_email(["a@example.com", "b@example.com"], "hi", "body") is True
    assert sent[0]["To"] == "a@example.com, b@example.com"
    assert sent[0]["From"] == "MindTech Robotics <portal@mindtechrobotics.com>"
    assert sent[0]["Reply-To"] == "support@mindtechrobotics.com"
