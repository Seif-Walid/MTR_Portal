# Staging — https://staging.portal.mindtechrobotics.com

A second, fully separate copy of the portal on the same Oracle VM as
production: its own Postgres, uploads, compose project (`portal-staging`) and
checkout (`~/MTR_Portal_staging`, branch `staging`). Use it to try changes —
especially Alembic migrations — against a copy of real data before they reach
production.

## How it's wired

```
browser ──HTTPS──> portal-caddy (prod stack, ports 80/443)
                     ├─ portal.mindtechrobotics.com          -> portal-frontend          (prod network)
                     └─ staging.portal.mindtechrobotics.com  -> portal-staging-frontend  (portal-edge network)
```

- DNS: Cloudflare `A staging.portal -> 130.110.17.255`, **DNS only** (grey
  cloud). Cloudflare's free certificate doesn't cover second-level names, and
  Caddy needs to answer the ACME challenge itself.
- `deploy/Caddyfile` has a site block per hostname; upstreams are container
  names. Caddy gets a Let's Encrypt cert for staging automatically.
- `docker-compose.staging.yml` publishes no host ports; only its frontend joins
  the external `portal-edge` network that the production Caddy is also on.
- Staging backend: 1 uvicorn worker, small Postgres buffers (1 GB VM), and
  `MAIL_BACKEND=disabled` because its data is a copy of production.
- Search engines are told not to index it (`X-Robots-Tag: noindex`).

## Deploying

Push to the `staging` branch. CI runs the same tests + builds, pushes images as
`:<sha>` and `:staging`, then SSHes to the VM and runs
`docker compose -f docker-compose.staging.yml pull && up -d` in
`~/MTR_Portal_staging`. Production deploys (push to `main`) are untouched.

```bash
git push origin HEAD:staging          # deploy the current commit to staging
```

The `staging` GitHub environment can get required reviewers like
`production` if wanted.

## Refreshing staging data from production

On the VM:

```bash
cd ~/MTR_Portal_staging && bash deploy/staging-clone-prod-db.sh
```

Drops the staging DB, restores a `pg_dump` of production into it, copies the
uploads volume, and restarts the staging backend (which runs `alembic upgrade
head`, so pending migrations are exercised on real data).

## Google sign-in on staging

Uses the same OAuth client as production. Google only accepts listed redirect
URIs, so add this one in Google Cloud Console → APIs & Services → Credentials →
the OAuth client → Authorized redirect URIs:

```
https://staging.portal.mindtechrobotics.com/api/auth/google/callback
```

Email/password sign-in works without it.

## Tearing it down

```bash
cd ~/MTR_Portal_staging && docker compose -f docker-compose.staging.yml down      # keep data
cd ~/MTR_Portal_staging && docker compose -f docker-compose.staging.yml down -v   # also delete staging data
```

Caddy keeps serving production; the staging hostname returns 502 until the
stack is back.
