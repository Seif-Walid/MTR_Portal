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
  subtree) or declines with a reason. The requester tracks the resulting task.
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

## Quick start

### 1. Database

```powershell
docker compose up -d          # PostgreSQL 16 on localhost:5432 (portal/portal)
```

No Docker? Set `DATABASE_URL=sqlite:///./portal_dev.db` in `backend/.env` (dev only).

### 2. Backend

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

### 3. Frontend

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

- **Register** on the login page (name, email, password), or
- **Continue with Google** — first sign-in auto-creates the account.

Either way, new accounts start with **no roles and no hierarchy position**: they can
sign in and send requests, but can't be tasked or see anyone else's work until the
admin assigns roles, a department, and a manager in User Management. Deactivated
accounts are blocked on both login paths.

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
   ```
4. Restart the backend. The "Sign in with Google" button on the login page enables
   itself automatically (it reads `GET /api/auth/config`).

## Tests

```powershell
cd backend
.venv\Scripts\python -m pytest tests -q
```

84 tests cover the permission layer: assignment allowed/denied (down, up, across,
self), subtree visibility and drill-down, request accept/decline/delegate, status
workflow rights (assignee vs. reviewer), multi-role union, hierarchy moves and
cycle rejection; inventory scoping, allocation capacity math, over-allocation/shrink
guards, and the who-holds-what breakdown; competition nesting with competition-scoped
PM / team-lead authority (a lead touches only their team); Google Sheet import (mocked)
with upsert; the **Positions** org tree (single root, no cycles, occupant→manager
derivation with vacant-seat skip, audit log); and admin/CEO-wide user management.

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
- `GET/POST /tasks` · `GET/PATCH /tasks/{id}` · `PATCH /tasks/{id}/status`
  · `POST /tasks/{id}/attachments` · `GET /tasks/attachments/{id}`
- `GET/POST /requests` · `POST /requests/{id}/accept` · `POST /requests/{id}/decline`
- `GET/POST /inventory` · `GET/PATCH/DELETE /inventory/{id}` — items (scoped by role)
  · `POST /inventory/{id}/allocations` · `PATCH/DELETE /inventory/allocations/{id}`
  · `GET /inventory/holders` · `GET /inventory/sheets/status` · `POST /inventory/sync`
  · `POST /inventory/import/preview` · `POST /inventory/import`
- `GET/POST /competitions` · `GET/PATCH/DELETE /competitions/{id}` (nested detail)
  · `POST/DELETE /competitions/{id}/pms` · `POST /competitions/{id}/categories`
  · `DELETE /competitions/categories/{id}` · `POST /competitions/categories/{id}/teams`
  · `PATCH/DELETE /competitions/teams/{id}` · `POST/DELETE /competitions/teams/{id}/members`
- `GET /org/tree` · `POST /org/positions` · `PATCH/DELETE /org/positions/{id}` · `GET /org/audit`
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
