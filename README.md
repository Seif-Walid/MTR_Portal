# Mind·Tech Robotics — Operations Portal

Standalone internal portal: task management, **inventory tracking**, org-hierarchy-based
access control, and per-role dashboards. Modular monolith — **inventory** ships as a
sibling domain sharing auth, users, and the permission layer; **finance** can be added
the same way.

**Stack:** FastAPI · SQLAlchemy 2 · Alembic · PostgreSQL · React + TypeScript (Vite) · Ant Design

Branded in the Mind-Tech black/white palette with red accents (see
`frontend/src/theme/brand.ts`), with a **light/dark mode toggle** (persisted per
browser, defaults to the OS preference). The logo lives at
`frontend/public/logo.png` and is rendered through
`frontend/src/components/Logo.tsx`.

## How permissions work

Everything derives from one data-driven tree (`users.manager_id`):

- **Tasks flow down** — you can task anyone in your recursive subtree, and only them.
- **Requests flow up/across** — anyone can request work from staff they *can't* task.
  The recipient accepts (spawns a task they own, optionally delegated into their own
  subtree) or declines with a reason. The requester tracks the resulting task. A request
  can optionally attach an **inventory item + quantity** (searchable across the whole
  catalogue, not just what you can normally see — the request is exactly how you ask for
  something outside your reach); it's informational context for the recipient, not a
  checkout — issuing that item still goes through Inventory → Requests.
- **Visibility** — own tasks + everything in your subtree, computed by a recursive CTE.
- **Multi-role users** hold the union of their roles (one tree node, e.g. CTO + Software Lead).
- **Admin** is a technical account outside the tree: user management + full access.

Moving a person in the tree instantly changes who can see and task them. No code or
permission changes. All rules are enforced server-side in the API; the UI only hides what
the API already forbids.

The **Organization** page (`/organization`) is a chart of **positions** (jobs): a title
with an optional occupant and a parent — a vacant seat still exists. **CEO and Admin** add
positions, assign occupants, mark a position technical, and drag to re-parent (no cycles,
single root, leaf-only delete). Assigning or moving a position **derives** each occupant's
`manager_id`, so the permission engine (which runs on the people tree) stays in sync — one
editable structure. Every structural change is written to an `OrgAuditLog`. People are still
given roles/accounts in the admin's **User Management** table.

## Audit log & soft delete

Beyond the org-structure log above, a general **Audit Log** (admin-only, `/admin/audit`)
records every **permission change** (role, manager, active/inactive), **inventory quantity
change**, and **competition-role change** (PM/lead/member) — actor, before/after, when.

**Delete defaults to soft delete**: inventory items and competition teams carry a
`deleted_at` — removing one hides it everywhere (it's invisible via the normal API) but
keeps its allocation / stock-movement / checkout-request / membership history intact,
since those rows reference it. A **permanent** hard delete (`?permanent=true`, or the
"Permanently delete (admin)" button) is available for genuine mistakes and is **admin-only**.
Users are already soft-deleted via `is_active`; competitions have their own `archived`
status and a can't-delete-while-referenced guard, so they didn't need a second mechanism.

## Inventory

The portal is the **single source of truth** for equipment. Each item carries a total
pool (e.g. 100 Arduinos) that is split into **allocations** — chunks checked out to a
purpose (training, competition, R&D, borrowed, other), optionally labelled (which
competition/project) and optionally held by a named person. From that the API computes
**in-use** and **free** counts and a per-purpose breakdown, so a 100-board pool reads as
*50 training · 30 competition · 10 R&D · 5 borrowed → 5 free*, and you can see that
*Salma has 2 in R&D and 1 in a competition*.

Access follows the same hierarchy:

- **Staff get full storage** — see every item, create/edit/delete, manage allocations,
  and push to Google Sheets.
- **Non-staff (students, competition members) see only their dedicated stuff** — items
  *designated to a team lead on their manager chain*, read-only. General-storage items
  (no designation) are invisible to them (404, so existence isn't leaked).

Capacity is guarded server-side: you can't allocate more than is free, and you can't
shrink an item's total below what's already in use.

**Whereabouts** is tracked by an append-only **stock-movement ledger**: each item's
drawer shows on-hand **by location and by holder**, derived by summing movements — never
stored, so it always reconciles. Record a movement (stock-in, move, issue, consume, return)
from a source (location / holder / nowhere) to a destination; a move out of a place can't
exceed what's on hand. Items carry a **low-stock threshold** (Inventory → **low-stock list**
for staff); **Locations** (rooms/shelves/boxes) are managed from the Inventory page.
`Item.quantity` is what the org *owns*; the ledger is *where those units are*.

**Checkout requests** ("Requests" button on the Inventory page) run the borrow lifecycle on
top of that ledger: anyone can **request** an item (quantity, reason, needed-by, return-by)
from its drawer; an inventory manager **approves or rejects**; **issuing** an approved
request is the *only* way it creates a movement (staff pick which location it comes from,
capped at what's on hand there); the requester or a manager later **returns** it to a
location, which is the only way that movement reverses. An issued request past its
return-by date shows as **overdue**.

**Competitions** nest `Competition → Category → Team → members`. Expand a competition to
add categories, add teams under a category, appoint a team lead, and assign members.
Authority is **scoped to the competition**, not global:

- **High staff** create competitions and appoint the **Project Managers** (the creator is
  auto-made a PM, so there's always one).
- A **PM** (or admin/CEO) runs that competition's structure — categories, teams, leads.
- A **Team Lead** manages only their own team's members (a lead can be a non-staff member).

Being a lead/PM in one competition grants nothing in another. A competition-purpose
inventory allocation links to a competition (its name flows to the Holdings matrix and
Sheets); a competition referenced by an allocation can't be deleted — archive it instead.

### Import components from a Google Sheet

Staff can bulk-import inventory from a spreadsheet (Inventory → **Import from Sheet**):
paste the Sheet link, preview the detected columns, map them to item fields (name is
required; quantity/category/unit/location/asset-tag/condition optional), optionally
dedicate everything to a team, and import. Re-running upserts (matched by asset tag, then
name) so it's safe to import repeatedly. The sheet must be shared with the service account
(same key as the sync below).

### Google Sheets mirror (app is king)

"Sync to Sheets" (staff only) overwrites a linked spreadsheet with the current
inventory snapshot — total / in-use / free / usage breakdown / holders per item — so
anyone who prefers a spreadsheet can read it, while real edits always happen in the
portal. It's optional and degrades gracefully: without credentials the button is
disabled. To enable, set in `backend/.env`:

```
GOOGLE_SHEETS_CREDENTIALS_FILE=/path/to/service-account.json
GOOGLE_SHEETS_SPREADSHEET_ID=<the id from the sheet URL>
GOOGLE_SHEETS_WORKSHEET=Inventory
```

Create a Google Cloud **service account**, download its JSON key, enable the Google
Sheets API, and **share the target spreadsheet with the service account's email**.

## Data Sync / Rebuild from Sheets

Beyond the inventory-only mirror above, an org manager (admin or CEO) can mirror the
portal's full **structural data** — people, positions, competitions, categories,
teams, PMs, team members, inventory locations, inventory items, and inventory
movements — to a multi-tab spreadsheet from **Admin → Data Sync**, and, in the other
direction, **rebuild the entire database from that spreadsheet**. This uses the same
service-account credentials as the inventory mirror above; nothing extra to configure.

- **Export** (`Sync all tabs`) pushes the current database out, one tab per entity,
  preserving each row's real database ID so cross-references (a team's PM, a
  position's parent, a movement's item) stay resolvable in the sheet.
- **Rebuild** (`Rebuild from Sheets…`) is the opposite, **destructive** direction: it
  replaces the database with whatever is in the sheet. This is a restore from
  spreadsheet, not a two-way sync — anything created in the portal since the last
  export and not present in the sheet is destroyed.
  1. **Dry-run** parses and cross-validates every tab (unknown roles, dangling
     references, bad enum values, cyclical positions, ...) and reports counts and
     errors without touching the database.
  2. If there are no errors, typing the org's exact name to confirm unlocks
     **commit**, which snapshots every managed table to a timestamped JSON file
     under `backend/snapshots/` (gitignored — treat it like `.env`, it can contain
     real org data), clears/de-references anything that depends on the data being
     replaced (tasks, requests, notifications, sessions, inventory allocations and
     checkout requests, audit-log actor references), truncates and re-imports the
     ten structural tables with the sheet's IDs preserved, and finally re-exports
     so the sheet and database are provably identical again.
  3. Everyone is signed out by a commit (every session is invalidated), and rebuilt
     accounts get a password nobody knows — sign back in via Google (if linked and
     within the allowed domains) or the "forgot password" flow.
- **Permissions**: export, dry-run, and rebuild history are available to any org
  manager (admin or CEO); **commit is one step stricter** — only `is_admin` or
  `is_ceo` specifically — matching the phrase-confirmation gate in the UI.
- Degrades the same way as the inventory mirror: without credentials configured,
  every `/sync/*` action beyond `status` returns a clear "not configured" error
  instead of silently doing nothing.

## Quick start

### Option A — Docker (everything at once)

```bash
docker compose up -d --build
```

Builds and starts all three services — Postgres, the backend (migrations + a clean
`app.seed` run automatically before it starts serving), and the frontend (built and
served via nginx, which also reverse-proxies `/api` to the backend so the browser only
ever talks to one origin — same as the Vite dev proxy below, just in production form).

- Frontend: **http://localhost:8080**
- Backend / API docs: **http://localhost:8000/docs**
- Postgres: **localhost:5432** (portal/portal) — change with `DB_PORT` if that's taken
  (`DB_PORT=5433 docker compose up -d --build`)

Drop a `backend/.env` next to `backend/Dockerfile` before starting (copy it from
`.env.example`) to carry over Google/Sheets credentials, `ORG_NAME`, or
`SEED_ADMIN_EMAIL`/`SEED_ADMIN_PASSWORD` into the containers — `DATABASE_URL` and
`FRONTEND_URL` are always overridden by `docker-compose.yml` regardless, since those two
have to match the container network no matter what's in your local dev `.env`. Set
`SEED_DEMO=1` (in that same `.env`, or `SEED_DEMO=1 docker compose up -d --build`) to load
the sample org instead of the clean one-admin seed.

`docker compose down` stops everything; add `-v` to also drop the Postgres volume (full
reset). Logs: `docker compose logs -f backend` (or `db` / `frontend`).

### Option B — run each piece directly (hot reload, no Docker)

#### 1. Database

```powershell
docker compose up -d db        # PostgreSQL 16 on localhost:5432 (portal/portal)
```

No Docker? Set `DATABASE_URL=sqlite:///./portal_dev.db` in `backend/.env` (dev only).

#### 2. Backend

```powershell
cd backend
py -3.13 -m venv .venv
.venv\Scripts\pip install -r requirements-dev.txt
copy .env.example .env
.venv\Scripts\alembic upgrade head        # apply migrations
.venv\Scripts\python -m app.seed          # roles + one admin account (real-ready)
.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000
```

`python -m app.seed` seeds a **clean, real-ready database**: the roles plus a single
technical-admin login (email/password overridable via `SEED_ADMIN_EMAIL` /
`SEED_ADMIN_PASSWORD`, default `admin@org.local` / `portal123` — change these for a real
deployment). You then add real users, teams, and inventory through the app — nothing is
hardcoded. To load the sample org for exploring/testing instead, run
`python -m app.seed --demo`.

#### 3. Frontend

```powershell
cd frontend
npm install
npm run dev                   # http://localhost:5173 (proxies /api to :8000)
```

### Default login

The clean seed creates one account — `admin@org.local` (password `portal123`) — the
technical admin, from which you create everyone else in User Management.

### Demo logins (`--demo` only, password: `portal123`)

Running `python -m app.seed --demo` adds a sample org for exploration:

| Email | Who |
|---|---|
| `ceo@org.local` | CEO — sees everything |
| `cto@org.local` | **Multi-role**: CTO + Software Lead |
| `mech.lead@org.local` | Mechanical Lead |
| `sw.emp@org.local` | Software employee (leaf) |
| `pm@org.local` | Project Manager |
| `teamlead@org.local` | Team Lead (under PM) |
| `student@org.local` | Student (under Team Lead) |

Also seeded by `--demo`: `cfo@`, `media@`, `elec.lead@`, `mech.emp@`, `elec.emp@`,
`media.emp@`, `fin.emp@`, `comp@` — all `@org.local` — plus sample tasks, a request, and
the 100-Arduino inventory example.

## Accounts & sign-in

There are no organization-issued emails — people join with personal addresses:

- **Register** on the login page (name, email, password) — open self-signup, or
- an **admin creates the account** in User Management.

Either way, new accounts start with **no roles and no hierarchy position**: they can
sign in and send requests, but can't be tasked or see anyone else's work until the
admin assigns roles, a department, and a manager. Deactivated accounts are blocked on
every sign-in path.

**Google sign-in is a second open-signup path**, same as Register: a verified Google
email with no existing portal account gets a fresh account on the spot — no roles, no
hierarchy position, same starting state as registering with a password. `GOOGLE_ALLOWED_DOMAINS`
is the only gate on who that applies to (see below). An existing **password**
account's first Google sign-in doesn't log you in, though: sign in with the password
once, then choose **Link Google account** from the account menu — only after that
explicit link does Google sign-in work for that account. This avoids ever matching an
account by email address alone.

## Sign in with Google (optional)

To enable the Google button:

1. In Google Cloud Console → APIs & Services → Credentials, create an
   **OAuth 2.0 Client ID** (type: Web application).
2. Add `http://localhost:8000/api/auth/google/callback` to its authorized redirect
   URIs (use your real backend URL in production).
3. Set in `backend/.env`:
   ```
   GOOGLE_CLIENT_ID=<client id>
   GOOGLE_CLIENT_SECRET=<client secret>
   FRONTEND_URL=http://localhost:5173
   # optional: restrict which domains may sign in with Google at all
   # GOOGLE_ALLOWED_DOMAINS=mindtechrobotics.org,gmail.com
   ```
4. Restart the backend. The "Sign in with Google" button on the login page enables
   itself automatically (it reads `GET /api/auth/config`).

## Tests

```powershell
cd backend
.venv\Scripts\python -m pytest tests -q
```

140 tests cover the permission layer: assignment allowed/denied (down, up, across,
self), subtree visibility and drill-down, request accept/decline/delegate, status
workflow rights (assignee vs. reviewer), multi-role union, hierarchy moves and
cycle rejection; inventory scoping, allocation capacity math, over-allocation/shrink
guards, the who-holds-what breakdown, and the stock-movement ledger with checkout
requests (submit→approve/reject→issue→return, overdue); competition nesting with
competition-scoped PM / team-lead authority (a lead touches only their team); Google
Sheet import (mocked) with upsert; the **Positions** org tree (single root, no cycles,
occupant→manager derivation with vacant-seat skip, audit log); admin/CEO-wide user
management, sourced from a DB-backed role/department catalog (not a hardcoded
frontend list); the general audit log + soft-delete-by-default with admin-only
permanent delete; Google sign-in (auto-provisions a no-roles account for any
verified email, gated only by the domain allowlist, and requires an explicit link —
never a silent email match — for an email that already has a password account, with
the OAuth round-trip mocked); the Sheets export/rebuild cycle — org-manager-only
export and dry-run, admin/CEO-only commit gated on an exact confirm phrase,
cross-tab reference validation, and a full rebuild round-trip (snapshot → clear
dependents → truncate → import → auto re-export) with Sheets I/O mocked; and task
blocked/comments/history/team-assignment — toggle rights, comment visibility
matching task visibility, the history trail ordering and its
participant-not-admin-only access, multi-assignee batch creation (atomic on a bad
assignee, batch view limited to the assigner).

Every test runs with Google OAuth forced to "unconfigured" regardless of what's in
your local `backend/.env` (an autouse fixture in `conftest.py`) — the suite never
depends on real credentials being present or absent on the machine running it.

## Project layout

```
backend/
  app/
    core/                  config, database, security
    domains/
      auth/                sessions, login, current-user deps
      users/               users, roles, admin CRUD
      hierarchy/           recursive-CTE subtree engine + /team views
      tasks/               tasks, workflow, attachments
      requests/            up/across requests -> spawned tasks
      notifications/       in-app notifications
      inventory/           items + allocations, capacity, Sheets sync + import
      competitions/        first-class competitions linked from allocations
      positions/           org-chart Position tree, resync_managers() bridge
      audit/               general audit log (domain/action/entity, JSON detail)
      sync/                multi-tab Sheets export + destructive rebuild
      (finance/)           future module — same pattern
    seed.py
  alembic/                 migrations
  tests/                   permission-layer test suite
frontend/
  src/
    api/                   typed REST client
    auth/                  session context
    components/            layout, task/inventory drawers, modals, notification bell
    pages/                 Tasks, Inventory, Competitions, Requests, Team,
                           Organization (org-tree), Admin Users, Login
```

## API surface (all under `/api`)

- `POST /auth/login` · `POST /auth/logout` · `GET /auth/me`
- `GET/POST /tasks` (`TaskCreate.assignee_ids` — one or more; >1 = a linked team
  assignment) · `GET/PATCH /tasks/{id}` · `PATCH /tasks/{id}/status`
  · `PATCH /tasks/{id}/blocked` · `POST /tasks/{id}/comments`
  · `GET /tasks/{id}/history` · `GET /tasks/batch/{batch_id}` (assigner/admin only)
  · `POST /tasks/{id}/attachments` · `GET /tasks/attachments/{id}`
- `GET/POST /requests` · `POST /requests/{id}/accept` · `POST /requests/{id}/decline`
  (`RequestCreate` accepts an optional `item_id` + `quantity`)
- `GET/POST /inventory` · `GET/PATCH/DELETE /inventory/{id}` — items (scoped by role)
  · `GET /inventory/directory` (unscoped id/name/unit, for pickers)
  · `POST /inventory/{id}/allocations` · `PATCH/DELETE /inventory/allocations/{id}`
  · `GET /inventory/holders` · `GET /inventory/sheets/status` · `POST /inventory/sync`
  · `POST /inventory/import/preview` · `POST /inventory/import`
  · `GET/POST /inventory/locations` · `DELETE /inventory/locations/{id}`
  · `GET /inventory/{id}/whereabouts` · `GET/POST /inventory/{id}/movements`
  · `GET /inventory/low-stock`
  · `GET/POST /inventory/requests` · `POST /inventory/requests/{id}/approve`
  · `POST /inventory/requests/{id}/reject` · `POST /inventory/requests/{id}/issue`
  · `POST /inventory/requests/{id}/return`
- `GET/POST /competitions` · `GET/PATCH/DELETE /competitions/{id}` (nested detail)
  · `POST/DELETE /competitions/{id}/pms` · `POST /competitions/{id}/categories`
  · `DELETE /competitions/categories/{id}` · `POST /competitions/categories/{id}/teams`
  · `PATCH/DELETE /competitions/teams/{id}` · `POST/DELETE /competitions/teams/{id}/members`
- `GET /org/tree` · `POST /org/positions` · `PATCH/DELETE /org/positions/{id}` · `GET /org/audit`
- `GET /audit` — admin-only general audit log (permissions / inventory quantity / competition roles)
- `GET /sync/status` (any user) · `GET /sync/exports` · `POST /sync/export` · `GET /sync/rebuild/history`
  (org manager: admin or CEO) · `POST /sync/rebuild/dry-run` (org manager, read-only)
  · `POST /sync/rebuild/commit` (admin/CEO only, requires exact `confirm_phrase`) — see
  [Data Sync / Rebuild from Sheets](#data-sync--rebuild-from-sheets) below
- `GET /team` — subtree members with per-status task counts
- `GET /team/tree` — nested org chart (admin: whole org; others: own subtree)
- `GET /users/assignable` (my subtree) · `GET /users/staff` (request recipients)
- `GET/POST/PATCH /users` — admin only
- `GET /notifications` · `GET /notifications/unread-count` · `POST /notifications/mark-read`

Interactive docs: http://localhost:8000/docs

## Task workflow

`To Do → In Progress → Submitted for Review → Approved / Revision Requested`

The assignee drives progress; only the assigner **or anyone above the assigner** can
approve or request revision. Every assignment, status change, and request resolution
produces an in-app notification.

**Blocked** is a flag on top of status, not a workflow step — a task can be blocked
while still `To Do` or `In Progress`. The assignee, the assigner, or an admin can mark
it blocked (with a reason) or clear it; the other side gets notified either way.

**Comments** are open to anyone who can already see the task — not just the assigner
and assignee. Post one from the task drawer; the other side is notified.

**History** shows every status change, edit, and blocked/unblocked toggle for a task,
newest first, visible to the task's own participants (not admin-only, unlike the
general audit log). It's the same audit trail mechanism as [Audit log & soft
delete](#audit-log--soft-delete), just scoped and exposed per-task.

**Team assignment**: pick more than one person when assigning a task (Tasks → Assign
task) and the portal creates one independent task per person — each moves through the
workflow on their own — linked as a batch so the assigner can see everyone's progress
together from any one of the tasks in the group.
