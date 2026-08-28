# Direct-HTTPS deployment (replaces Tailscale Funnel + Cloudflare Pages proxy)

Goal: browser → `https://portal.mindtechrobotics.com` → **the VM, one hop**. No
relay, no double proxy, no third-party-cookie problem (frontend and API are
same-origin).

Run everything below **on the Oracle VM** unless noted.

## 1. Public hostname (Cloudflare DNS, the `mindtechrobotics.com` zone)

The portal lives on a subdomain of the club domain; the apex serves the
marketing site (Cloudflare Pages):

```
mindtechrobotics.com          -> marketing site  (Cloudflare Pages)
portal.mindtechrobotics.com   -> portal          (this VM, one hop)
```

| Type | Name   | Content          | Proxy status              |
|------|--------|------------------|---------------------------|
| A    | portal | 130.110.17.255   | **DNS only** (grey cloud) |

> Must be **grey-cloud / DNS-only**. Caddy fetches its own Let's Encrypt cert on
> the VM over ports 80/443; Cloudflare's orange-cloud proxy would intercept the
> ACME challenge and terminate TLS itself.

If the VM's public IP ever changes, edit that A record — it is a static record,
there is no updater daemon to install.

## 2. Open ports 80 + 443

**Oracle Cloud console** → your VCN → the instance's subnet → Security List →
add two Ingress rules: source `0.0.0.0/0`, TCP, destination ports **80** and **443**.

**On the VM** (Oracle Ubuntu images ship with a restrictive iptables REJECT rule):

```bash
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80  -j ACCEPT
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
sudo netfilter-persistent save
```

Verify from your laptop: `nc -vz portal.mindtechrobotics.com 443` should connect.

## 3. Deploy

```bash
cd ~/MTR_Portal          # wherever the repo lives on the VM
git pull                 # picks up deploy/Caddyfile + docker-compose.prod.yml

export SITE_ADDRESS=portal.mindtechrobotics.com

# Google SSO: the Client ID is baked into docker-compose.prod.yml, but the
# secret is never committed. Generate/copy it in Google Cloud Console
# (APIs & Services > Credentials > your OAuth client > "Add secret") and
# export it here. Compose refuses to start if this is unset.
export GOOGLE_CLIENT_SECRET=paste-the-secret-here

docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

Caddy fetches a Let's Encrypt cert automatically on first boot (needs step 1 + 2
done first, so DNS resolves and port 80 is reachable). Watch it:

```bash
docker logs -f portal-caddy      # look for "certificate obtained successfully"
```

## 4. Verify (should be ~5-10x faster than the Funnel path)

```bash
curl -s -o /dev/null -w 'ttfb=%{time_starttransfer}s total=%{time_total}s\n' \
  https://portal.mindtechrobotics.com/api/auth/config
```

Then open `https://portal.mindtechrobotics.com` in a browser, log in, confirm
`/me` stays 200.

## 5. Retire the old paths

- Point people at `https://portal.mindtechrobotics.com` (Cloudflare Pages for the
  portal can be deleted; the marketing Pages project stays).
- Turn off the Funnel so nothing depends on it:
  ```bash
  sudo tailscale funnel off
  ```
- The former `mindtechrobotics.duckdns.org` host is retired — Caddy no longer
  answers for it. See [SUBDOMAIN_CUTOVER.md](SUBDOMAIN_CUTOVER.md) for the
  cutover history and the remaining external cleanup (DuckDNS record, old Google
  redirect URI).
- Optional code cleanup once you're happy: delete `frontend/functions/api/[[route]].ts`
  (the Pages proxy) — it's unused in this architecture.

## Rollback

`docker compose -f docker-compose.yml -f docker-compose.prod.yml down` and bring the
old stack back with `docker compose up -d`; re-enable Funnel. Nothing here touches the
database volume.
