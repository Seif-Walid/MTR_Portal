# Cutover: move the portal to `portal.mindtechrobotics.com`

Today the portal answers on `mindtechrobotics.duckdns.org`; the marketing site
owns `mindtechrobotics.com` (Cloudflare Pages). This moves the portal onto a
subdomain of the same brand domain, so the two apps share one domain:

```
mindtechrobotics.com          -> marketing site  (Cloudflare Pages)
portal.mindtechrobotics.com   -> portal          (the Oracle VM, one hop)
```

Nothing in the code is hard-coded to the old host — Caddy, the backend
`FRONTEND_URL`, the CORS origin and the Google redirect URI are all derived from
`SITE_ADDRESS` at deploy time. So the cutover is DNS + Google + one redeploy.
The duckdns host keeps working until you retire it, so this is zero-downtime.

## 1. DNS (Cloudflare, the `mindtechrobotics.com` zone)

Add a record for the subdomain pointing at the VM's public IP (`130.110.17.255`):

| Type | Name   | Content          | Proxy status              |
|------|--------|------------------|---------------------------|
| A    | portal | 130.110.17.255   | **DNS only** (grey cloud) |

> Must be **grey-cloud / DNS-only**. Caddy fetches its own Let's Encrypt cert on
> the VM (port 80/443 direct); Cloudflare's orange-cloud proxy would intercept
> the ACME challenge and terminate TLS itself. Grey cloud = one hop to the VM,
> same as the duckdns path today.

Verify from your laptop before deploying:
```bash
dig +short portal.mindtechrobotics.com   # -> 130.110.17.255
nc -vz portal.mindtechrobotics.com 443
```

## 2. Google OAuth (Google Cloud Console → Credentials → the portal OAuth client)

Add an **Authorized redirect URI** (keep the old one until the site is retired):
```
https://portal.mindtechrobotics.com/api/auth/google/callback
```
The Client ID is already baked into `docker-compose.prod.yml`; only the redirect
URI list needs the new entry. The backend computes `GOOGLE_REDIRECT_URI` from
`SITE_ADDRESS`, so no code change.

## 3. Redeploy the portal with the new hostname (on the VM)

```bash
cd ~/MTR_Portal
git pull
export SITE_ADDRESS=portal.mindtechrobotics.com
export GOOGLE_CLIENT_SECRET=…            # same secret as before
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
docker logs -f portal-caddy              # wait for "certificate obtained successfully"
```

Caddy provisions a fresh cert for the new name automatically (steps 1+2 must be
done first so DNS resolves and the ACME challenge on :80 reaches the VM).

Verify:
```bash
curl -s -o /dev/null -w '%{http_code}\n' https://portal.mindtechrobotics.com/api/health
curl -s https://portal.mindtechrobotics.com/api/public/hall-of-fame | head -c 100
```

## 4. Point the website at the new API origin

In the **MTR_Website** repo, set the Cloudflare Pages env var (Production **and**
Preview) and redeploy:
```
PORTAL_API_URL = https://portal.mindtechrobotics.com
```
(`lib/roster.ts` reads this; it falls back to the bundled `roster.json` if unset.)
Also update `.env.example` / `.env.local` in that repo for local dev parity.

## 5. Retire the old host (optional, after a few days)

Once `portal.mindtechrobotics.com` is verified and the website reads it, you can
drop the DuckDNS updater cron and stop advertising the old URL. Keep the DuckDNS
record a while as a fallback; Google's old redirect URI can be removed last.
```
```
