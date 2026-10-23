"""Outbound email for the portal.

One entry point, `send_email`, with a transport chosen by `MAIL_BACKEND`:

- `disabled` (default): log and drop, so dev/CI never send real mail.
- `cloudflare`: Cloudflare Email Sending REST API (domain already lives on
  Cloudflare DNS, so SPF/DKIM are added automatically on onboarding).
- `smtp`: any SMTP relay (Google Workspace, Resend, Brevo, ...).

Sending never raises into the caller: a mail outage must not fail the request
that triggered it. Callers get a bool back and the failure is logged.
"""

import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr

import httpx

from app.core.config import settings

log = logging.getLogger(__name__)

CLOUDFLARE_SEND_URL = "https://api.cloudflare.com/client/v4/accounts/{account_id}/email/sending/send"


def _sender(from_addr: str | None, from_name: str | None) -> tuple[str, str]:
    return (from_addr or settings.mail_from_address, from_name or settings.mail_from_name)


def _send_cloudflare(
    to: list[str], subject: str, text: str, html: str | None, sender: tuple[str, str],
    reply_to: str | None,
) -> None:
    payload: dict = {
        "to": to,
        "from": {"address": sender[0], "name": sender[1]},
        "subject": subject,
        "text": text,
    }
    if html:
        payload["html"] = html
    if reply_to or settings.mail_reply_to:
        payload["reply_to"] = reply_to or settings.mail_reply_to
    r = httpx.post(
        CLOUDFLARE_SEND_URL.format(account_id=settings.cloudflare_account_id),
        headers={"Authorization": f"Bearer {settings.cloudflare_api_token}"},
        json=payload,
        timeout=15,
    )
    body = r.json() if r.content else {}
    if r.status_code != 200 or not body.get("success", False):
        raise RuntimeError(f"cloudflare email send failed: {r.status_code} {body.get('errors')}")


def _send_smtp(
    to: list[str], subject: str, text: str, html: str | None, sender: tuple[str, str],
    reply_to: str | None,
) -> None:
    msg = EmailMessage()
    msg["From"] = formataddr((sender[1], sender[0]))  # sender is (address, name)
    msg["To"] = ", ".join(to)
    msg["Subject"] = subject
    if reply_to or settings.mail_reply_to:
        msg["Reply-To"] = reply_to or settings.mail_reply_to
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    if settings.smtp_ssl:
        with smtplib.SMTP_SSL(
            settings.smtp_host, settings.smtp_port, context=ssl.create_default_context(), timeout=15
        ) as s:
            _smtp_deliver(s, msg)
    else:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as s:
            s.starttls(context=ssl.create_default_context())
            _smtp_deliver(s, msg)


def _smtp_deliver(s: smtplib.SMTP, msg: EmailMessage) -> None:
    if settings.smtp_user:
        s.login(settings.smtp_user, settings.smtp_password)
    s.send_message(msg)


def send_email(
    to: str | list[str],
    subject: str,
    text: str,
    html: str | None = None,
    *,
    from_address: str | None = None,
    from_name: str | None = None,
    reply_to: str | None = None,
) -> bool:
    """Send one message. Returns True if the transport accepted it."""
    recipients = [to] if isinstance(to, str) else list(to)
    if not recipients:
        return False
    backend = settings.mail_backend.lower()
    sender = _sender(from_address, from_name)
    try:
        if backend == "cloudflare":
            _send_cloudflare(recipients, subject, text, html, sender, reply_to)
        elif backend == "smtp":
            _send_smtp(recipients, subject, text, html, sender, reply_to)
        else:
            log.info("mail disabled; dropped %r to %s", subject, recipients)
            return False
    except Exception:
        log.exception("mail send failed (%s) subject=%r to=%s", backend, subject, recipients)
        return False
    return True
