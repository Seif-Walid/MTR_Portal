# @mindtechrobotics.com email

Two halves. The domain's DNS lives on Cloudflare.

- **Receiving / staff addresses** — Cloudflare Email Routing (free). Any
  `name@mindtechrobotics.com` alias forwards to a real inbox.
- **Sending from the portal** — `backend/app/core/mail.py`, transport chosen by
  `MAIL_BACKEND` (`disabled` default, `cloudflare`, or `smtp`). Failures are
  logged and never raised into request handlers.

## Status (2026-10-23)

Done in the Cloudflare dashboard:

- Email Routing enabled; MX (`route1/2/3.mx.cloudflare.net`), SPF and DKIM
  records added to the zone.
- Destination `seifwalid64@gmail.com` verified.
- Rules: `support@` and `portal@` forward to that destination.

Not done: **outbound sending**. Cloudflare Email Sending needs the Workers Paid
plan (~$5/month), which is a billing decision for the account owner. Until a
sending backend is configured, `MAIL_BACKEND=disabled` and the portal sends
nothing.

## Add a staff address

Cloudflare → `mindtechrobotics.com` → Email → Email Routing:

1. Destination addresses → add the person's real inbox; they click the
   verification link Cloudflare emails them.
2. Routing rules → Create routing rule → `firstname` @ mindtechrobotics.com →
   Send to an email → their inbox.

Aliases receive mail only. Replying *as* `firstname@` needs a sending relay
(below) plus Gmail "Send mail as", or Google Workspace mailboxes instead.

## Pick a sending backend

| Option | Cost | Notes |
|---|---|---|
| Cloudflare Email Sending | Workers Paid ($5/mo) | `MAIL_BACKEND=cloudflare`; onboard domain in Email Service → Email Sending (adds SPF/DKIM); API token with Email Sending permission |
| Free SMTP relay (Resend, Brevo, ...) | Free tier | `MAIL_BACKEND=smtp`; create account, add the DNS records it gives you in Cloudflare DNS, use its SMTP creds |
| Google Workspace | Free for eligible nonprofits/education | Real mailboxes; MX becomes Google's (replace the Cloudflare routing MX), `MAIL_BACKEND=smtp` with an app password |

SPF note: a domain may have one SPF TXT record. Routing already created one
(`include:_spf.mx.cloudflare.net`); when adding a relay, merge its `include:`
into that record rather than adding a second.

Also add DMARC: TXT `_dmarc` = `v=DMARC1; p=none; rua=mailto:support@mindtechrobotics.com`.

## Zoho Mail (current choice)

Zoho now hosts the domain's mailboxes (`support@` is a Zoho group). To let the
portal send through it:

1. Zoho Mail admin → Users → create a mailbox user for the sender, we use
   `portal_support@mindtechrobotics.com` (SMTP needs a real user, not a group).
2. If that user turns on 2FA, generate an app password (My Account →
   Security → App Passwords) and use it as `SMTP_PASSWORD`.
3. On the VM, in `backend/.env`:

```
MAIL_BACKEND=smtp
MAIL_FROM_ADDRESS=portal_support@mindtechrobotics.com
MAIL_REPLY_TO=support@mindtechrobotics.com
SMTP_HOST=smtp.zoho.com        # smtppro.zoho.com answers 554 "Access Restricted" on this plan
SMTP_PORT=465
SMTP_SSL=true
SMTP_USER=portal_support@mindtechrobotics.com
SMTP_PASSWORD=<account or app password>
```

`MAIL_FROM_ADDRESS` must be the SMTP user (or an address Zoho lets it send
as), or Zoho rejects the message. Add Zoho's SPF `include:zoho.com` and DKIM
record in Cloudflare DNS as the Zoho admin console shows them.

Mail settings live only in `backend/.env` on the VM: `docker-compose.prod.yml`
deliberately doesn't set them, since compose `environment:` entries override
`env_file`.

Uses so far: forgot-password links (`POST /api/auth/forgot-password`).

## Enable in the portal

Set on the VM (`backend/.env` or exported before `docker compose up`):

```
MAIL_BACKEND=cloudflare            # or smtp
CLOUDFLARE_ACCOUNT_ID=...          # cloudflare backend
CLOUDFLARE_API_TOKEN=...
# smtp backend: SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_SSL
```

Smoke test after redeploy:

```
docker exec portal-backend python -c "from app.core.mail import send_email; print(send_email('you@example.com','test','hello'))"
```

`True` = accepted by the transport.
