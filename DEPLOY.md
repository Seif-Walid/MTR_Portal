# Deploying MTR Portal (free tier)

Three pieces: **frontend** (Cloudflare Pages), **backend** (Render), **database** (Neon Postgres).
The frontend and backend end up on the **same origin** — Cloudflare Pages serves the static site
*and* reverse-proxies `/api/*` to the backend (via `frontend/functions/api/[[path]].js`), so the
session cookie stays first-party and login works with no CORS/SameSite changes.

```
Browser ──▶ https://<you>.pages.dev
              ├─ static SPA            (Cloudflare Pages)
              └─ /api/*  ──proxy──▶  https://<you>.onrender.com  (Render, FastAPI)
                                        └──▶ Neon Postgres
```

---

## 0. Prerequisite — push to GitHub
Both hosts deploy from the repo `github.com/Seif-Walid/MTR_Portal`. Make sure `main` is pushed:
```bash
git add -A && git commit -m "Deploy config: Render port, Cloudflare proxy" && git push origin main
```

---

## 1. Backend — Render (free web service, no card)
> The container runs DB migrations + seeds an admin on startup, so it needs a database to boot.
> It will go green the moment `DATABASE_URL` (Neon, step 3) is set. You can create it now.

1. **render.com** → sign up (GitHub) → **New +** → **Web Service** → connect the repo.
2. Settings:
   - **Root Directory:** `backend`
   - **Runtime:** Docker (auto-detects `backend/Dockerfile`)
   - **Instance type:** Free
3. **Environment variables** (Settings → Environment):
   | Key | Value |
   |---|---|
   | `DATABASE_URL` | *(from Neon — step 3; leave blank until then)* |
   | `COOKIE_SECURE` | `true` |
   | `FRONTEND_URL` | `https://<your-project>.pages.dev` *(fill after step 2)* |
   | `SEED_ADMIN_EMAIL` | your real admin email |
   | `SEED_ADMIN_PASSWORD` | a strong password |
   | `ORG_NAME` | `Mind-Tech Robotics` |

   *(Render injects `PORT` automatically — the entrypoint already binds to it.)*
4. Deploy. Note the URL, e.g. `https://mtr-portal-api.onrender.com`.
   - **Cold start:** free services sleep after ~15 min idle; the first request then takes ~50s. Normal.
   - **Uploads caveat:** task-attachment files sit on the container's ephemeral disk and are lost on
     redeploy. Fine for now; later move `UPLOAD_DIR` to a persistent volume or object storage.

---

## 2. Frontend — Cloudflare Pages (free, no card)
1. **dash.cloudflare.com** → **Workers & Pages** → **Create** → **Pages** → **Connect to Git** → pick the repo.
2. Build settings:
   - **Root directory (advanced):** `frontend`
   - **Build command:** `npm run build`
   - **Build output directory:** `dist`
   - Framework preset: none/Vite is fine.
3. **Environment variable** (Settings → Environment variables → Production **and** Preview):
   | Key | Value |
   |---|---|
   | `BACKEND_URL` | your Render URL, e.g. `https://mtr-portal-api.onrender.com` |
4. Deploy. You get `https://<your-project>.pages.dev`.
   - `frontend/functions/api/[[path]].js` is auto-detected → `/api/*` is proxied to `BACKEND_URL`.
   - `frontend/public/_redirects` handles SPA deep links.
5. Go back to Render and set `FRONTEND_URL` to this Pages URL (used for OAuth/redirects). Redeploy the backend.

---

## 3. Database — Neon (free Postgres, no card)
See the chat walkthrough. In short:
1. **neon.tech** → new project → region **AWS Europe (Frankfurt)** (closest to Egypt).
2. **Connect** → turn **off** connection pooling → copy the connection string.
3. Change the scheme `postgresql://` → **`postgresql+psycopg://`** (keep `?sslmode=require`).
4. Put it in Render as **`DATABASE_URL`** → the backend redeploys, runs migrations, seeds the admin, goes green.

**Load the real data (307 members, 173 items, org, events):** the schema is now empty on Neon. A
one-time copy from the local SQLite `portal_dev.db` → Neon brings everything over (ask and a copy
script will be provided). Until then, you can log in with the seeded `SEED_ADMIN_*` account.

---

## Optional — Google sign-in
Password login works out of the box. For Google SSO, set on Render:
`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, and `GOOGLE_REDIRECT_URI=https://<your-project>.pages.dev/api/auth/google/callback`,
and register that redirect URI in the Google Cloud console. (It routes through the same proxy, so it
stays first-party.)

## Quick verification after all three are up
- Visit the Pages URL → login page loads (CIRCUIT styling).
- Log in with the `SEED_ADMIN_*` credentials → lands in the app.
- Open DevTools → Network: `/api/auth/me` returns 200 from the Pages origin (proxied). Cookie
  `portal_session` is set on the Pages domain.
