# Direct-HTTPS deployment (replaces Tailscale Funnel + Cloudflare Pages proxy)

Goal: browser → `https://<host>.duckdns.org` → **the VM, one hop**. No relay, no
double proxy, no third-party-cookie problem (frontend and API are same-origin).

Run everything below **on the Oracle VM** unless noted.

## 1. Free stable hostname (DuckDNS)

1. Go to https://www.duckdns.org, sign in (GitHub/Google), create a subdomain,
   e.g. `mtrportal` → you get `mtrportal.duckdns.org`. Copy your **token**.
2. Point it at the VM's public IP (either paste the IP on the DuckDNS page, or
   run the updater once):

   ```bash
   curl "https://www.duckdns.org/update?domains=mtrportal&token=YOUR_TOKEN&ip="
   ```

   (Empty `ip=` makes DuckDNS use the caller's public IP — run it from the VM.)
3. Keep it current in case the VM's public IP changes (cron, every 5 min):

   ```bash
   ( crontab -l 2>/dev/null; echo '*/5 * * * * curl -s "https://www.duckdns.org/update?domains=mtrportal&token=YOUR_TOKEN&ip=" >/dev/null' ) | crontab -
   ```

## 2. Open ports 80 + 443

**Oracle Cloud console** → your VCN → the instance's subnet → Security List →
add two Ingress rules: source `0.0.0.0/0`, TCP, destination ports **80** and **443**.

**On the VM** (Oracle Ubuntu images ship with a restrictive iptables REJECT rule):

```bash
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80  -j ACCEPT
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
sudo netfilter-persistent save
```

Verify from your laptop: `nc -vz mtrportal.duckdns.org 443` should connect.

## 3. Deploy

```bash
cd ~/MTR_Portal          # wherever the repo lives on the VM
git pull                 # picks up deploy/Caddyfile + docker-compose.prod.yml

export SITE_ADDRESS=mtrportal.duckdns.org
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
  https://mtrportal.duckdns.org/api/auth/config
```

Then open `https://mtrportal.duckdns.org` in a browser, log in, confirm `/me` stays 200.

## 5. Retire the old path

- Point people at `https://mtrportal.duckdns.org` (Cloudflare Pages can be deleted).
- Turn off the Funnel so nothing depends on it:
  ```bash
  sudo tailscale funnel off
  ```
- Optional code cleanup once you're happy: delete `frontend/functions/api/[[route]].ts`
  (the Pages proxy) — it's unused in this architecture.

## Rollback

`docker compose -f docker-compose.yml -f docker-compose.prod.yml down` and bring the
old stack back with `docker compose up -d`; re-enable Funnel. Nothing here touches the
database volume.
