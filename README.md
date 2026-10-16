# Mind·Tech Robotics — Operations Portal

Standalone internal portal: task management, **inventory tracking**, events and teams,
a shared **calendar**, an archive of past seasons, org-hierarchy-based access control,
and per-person dashboards. Modular monolith — **inventory** ships as a sibling domain
sharing auth, users, and the permission layer; **finance** can be added the same way.

**Stack:** FastAPI · SQLAlchemy 2 · Alembic · PostgreSQL · React + TypeScript (Vite) · Ant Design

The UI is the **CIRCUIT** design system (see `DESIGN.md`): a printed-circuit-board look
— near-black void background, translucent panels, electric-blue accent, monospace data
labels, red reserved strictly for alerts. It is **dark-only by design**; the theme
provider (`frontend/src/theme/ThemeContext.tsx`) exists but has a single mode, and the
tokens live in `frontend/src/theme/circuitTokens.ts` / `circuitTheme.ts`. The logo is at
`frontend/public/logo.png`, rendered through `frontend/src/components/Logo.tsx`.

Companion docs: **`PRODUCT.md`** (what the product is), **`DESIGN.md`** (the design
system), **`DECISIONS.md`** (judgment calls and why), **`deploy/RUNBOOK.md`** (how
production is actually deployed).

## How permissions work

Power comes from a **Discord-style access ladder** — data, not code. The *privileges* are
a fixed vocabulary the app can actually gate; the *levels* are admin-editable tiers on the
site, each a bundle of privileges. A person's **effective level** is the strongest of the
org seats they occupy plus an optional personal override; with neither, they get the
ladder's bottom rung. There is **no hardcoded role or job title anywhere** — a position
titled "CEO" grants nothing unless you gave that seat a level. Ships with a starting ladder
(Admin/Board/Lead/Member/Guest) you can rename, reorder, retoggle, add to, or delete.

The privilege vocabulary (`GET /api/access/privileges`, defined in
`backend/app/domains/access/service.py`):

| Group | Keys |
|---|---|
| Inventory | `inventory.view` · `inventory.request` · `inventory.approve` · `inventory.edit` |
| Events | `events.view` · `events.manage_seated` · `events.create` · `events.manage_any` |
| Tasks | `tasks.use` · `tasks.assign` · `tasks.assign_any` |
| Organization | `org.view` · `org.edit` |
| People | `people.view` · `users.manage` |
| Members | `members.view` · `members.edit` |
| Finance | `finance.view` · `finance.edit` |
| Dashboard | `dashboard.view` |
| Audit | `audit.view` |

- **Seats carry the power.** Every org position (real seat or automatic role) has an
  optional access level. Occupy the seat, get its level. New seats confer nothing by
  default, so building org structure never leaks authority.
- **Per-user override.** User Management can pin a level directly on a person (bootstrap
  admin, an advisor with no seat) — independent of any position.
- **Guests see nothing.** A fresh sign-up (or Google auto-provision) lands at the bottom
  rung with no privileges until someone grants more.

Two structural rules stay on the people tree (`users.manager_id`), separate from the ladder:

- **Tasks flow down** — you can task anyone in your recursive subtree (needs `tasks.assign`).
- **Requests flow up/across** — request work from anyone who uses tasks but whom you *can't*
  task directly. The recipient accepts (spawns a task) or declines. A request can attach an
  **inventory item + quantity** as context; issuing still goes through Inventory → Requests.

All rules are enforced server-side; the UI only hides what the API already forbids. The
**access ladder itself** (rename tiers, toggle any privilege, reorder, add/remove) lives in
the **User Management** page for anyone with `users.manage`; the top level always holds
every privilege and can't be edited away, and at least one top-level override must always
exist so no one can lock everyone out.

The **Organization** page (`/organization`) is a chart of **positions** (jobs): a title, an
optional access level, zero or more occupants, and a parent — a vacant seat still exists.
Anyone with `org.edit` adds positions, assigns occupants, sets a seat's access level, marks
a position technical, and drags to re-parent (no cycles, single root, leaf-only delete).
Assigning or moving a position **derives** each occupant's `manager_id`, so the task/
visibility tree stays in sync — one editable structure. Every structural change is written
to an `OrgAuditLog`. Accounts, their personal override, and the ladder itself are managed in
the **User Management** table.

## Home

`/home` is a triage roll-up, not a landing page: everything that needs the signed-in person
right now — **overdue**, **needs review**, **waiting on you**, **due today**, **this week** —
gathered across tasks, work requests, and inventory returns into one ranked list
(`GET /api/dashboard`). Each row links straight to the thing it's about.

## Audit log & soft delete

Beyond the org-structure log above, a general **Audit Log** (`audit.view`, `/admin/audit`)
records every **access change** (level override, manager, active/inactive), **inventory
quantity change**, and **role-occupant change** — actor, before/after, when.

**Delete defaults to soft delete**: inventory items and event teams carry a
`deleted_at` — removing one hides it everywhere (it's invisible via the normal API) but
keeps its allocation / stock-movement / checkout-request / membership history intact,
since those rows reference it. A **permanent** hard delete (`?permanent=true`, or the
"Permanently delete (admin)" button) is available for genuine mistakes and is **admin-only**.
Users are already soft-deleted via `is_active`; events have their own `archived`
status and a can't-delete-while-referenced guard, so they didn't need a second mechanism.

## Inventory

The portal is the **single source of truth** for equipment. Each item carries a total
pool (e.g. 100 Arduinos) that is split into **allocations** — chunks checked out to a
purpose (training, event, R&D, borrowed, other), optionally labelled (which
event/project) and optionally held by a named person. From that the API computes
**in-use** and **free** counts and a per-purpose breakdown, so a 100-board pool reads as
*50 training · 30 event · 10 R&D · 5 borrowed → 5 free*, and you can see that
*Salma has 2 in R&D and 1 in an event*.

Access is a straight privilege check, not a hierarchy walk:

- **`inventory.view`** (or `inventory.edit` / `inventory.approve`, which imply it) sees the
  **whole storage** — every item, its allocations, whereabouts and history.
- **Without any of those, nothing is visible** — item lookups 404 rather than leak that
  an item exists.
- **`inventory.edit`** is the management grant: create, edit, delete, allocate and import. **`inventory.approve`** covers approving requests and moving stock;
  **`inventory.request`** lets someone ask for units without seeing the controls.

Capacity is guarded server-side: you can't allocate more than is free, and you can't
shrink an item's total below what's already in use.

**Whereabouts** is tracked by an append-only **stock-movement ledger**: each item's
drawer shows on-hand **by location and by holder**, derived by summing movements — never
stored, so it always reconciles. Record a movement (stock-in, move, issue, consume, return)
from a source (location / holder / nowhere) to a destination; a move out of a place can't
exceed what's on hand. Items carry a **low-stock threshold** (Inventory → **low-stock list**);
**Locations** (rooms/shelves/boxes) are managed from the Inventory page.
`Item.quantity` is what the org *owns*; the ledger is *where those units are*.

**Checkout requests** ("Requests" button on the Inventory page) run the borrow lifecycle on
top of that ledger: anyone with `inventory.request` can **request** an item (quantity,
reason, needed-by, return-by) from its drawer; an approver **approves or rejects**;
**issuing** an approved request is the *only* way it creates a movement (the issuer picks
which location it comes from, capped at what's on hand there); the requester or a manager
later **returns** it to a location, which is the only way that movement reverses. An issued
request past its return-by date shows as **overdue**.

## Events

**Events** (Competition / Training / R&D — and anything else you add) nest
`Event → Category → Team → members`. The kind is an editable **EventKind** row, not an
enum: each kind has its own slug, tab, sort order, and its own labels for the event /
category / team / member nouns (a Training "Season → Group" reads differently from a
Competition "Event → Team"). Expand an event to add categories, add teams under a
category, and assign members with a per-member role.

Authority is **scoped to the event and derived from seats**, never from a job title:

- `events.create` creates events; `events.manage_any` is the blanket override.
- Creating an event auto-seats the configured **role chain** (see below) as real org-chart
  positions. Occupying such a seat, when its access level carries **`events.manage_seated`**,
  is what lets you manage *that* event or *that* team — an event-level seat runs the whole
  event's structure, a team-level seat touches only its own team.
- Being seated in one event grants nothing in another.

Events carry an official **`full_name`**, optional **awards**, and an **archived** status.
An event-purpose inventory allocation links to an event (its name flows to the Holdings
matrix); an event referenced by an allocation can't be deleted — archive it
instead.

### Automatic roles (the role-chain engine)

The org chart can seat itself. **Role templates** (`/api/org/roles/templates`, edited from
the Organization page) are admin-configured rows — a title template, a trigger
(event / team / member created), an order in the chain, an optional access level, and an
optional `event_kind_id` so a chain applies to one kind or to all. When an event, team, or
member is created, the engine creates the matching org **positions** under the previous
link in the chain, starting **vacant**; someone with `org.edit` (or whoever already manages
the linked event/team) fills the seat. Retitling, archiving, or deleting a template
reparents or splices the live tree instead of orphaning it. **Zero role names are hardcoded**
— delete every template and the feature simply does nothing.

## Archive & Hall of Fame

Archiving an event tears down its managing seats and moves it into the **Archive**
(`/archive`) — readable by **every signed-in member**, no privilege gate. An archived event
shows two things:

- **The record** — the full roster (teams, their placements, members and their competition
  roles) plus the event's awards and official title. Editing it is gated on the same
  privilege as reactivating (`events.create` or `events.manage_any`).
- **Your own participation** — the teams you were on and every task you held, tagged
  accomplished or incomplete. Personalized: it never shows anyone else's tasks.

The same projection is published, unauthenticated and PII-free, at
**`GET /api/public/hall-of-fame`** (+ `/summary`) for the marketing site at
`mindtechrobotics.com` — it exposes a member's public name and discipline and nothing
else, never contact details, national ID, guardian, birthday, user id or email. The record
shape lives in `app/domains/events/hall_of_fame.py`, shared with the Archive so the internal
and public views can never drift, and the headline counts (competitions, seasons, members,
medals) are **computed from the records**, never kept by hand.

## Calendar & team time blocks

`/calendar` overlays dated items from several sources on one month view
(`GET /api/calendar?scope=&sources=`): **tasks**, **events**, **inventory** (return dates),
**requests**, and **teams**. `scope=general` shows everything you may see; `scope=me` shows
only what you participate in. Each source re-checks its own privilege, so a source you
can't view is silently skipped rather than erroring.

**Time blocks** are how a team claims a stretch of the calendar. A block anchors to exactly
one team — an *event* team or an *org* unit (the position whose subtree is the team) — and
occupies either a continuous span (`start_date`…`end_date`) or only selected weekdays inside
that span (`weekday_mask`, bit *i* = Python weekday, Monday = 0). Blocks are expanded into
calendar items on read; no per-day rows are stored. Schedule them from **My Teams** →
TimeBlockPanel.

## Members — the roster (`/members`)

The member database lives in the portal. Each member is a **roster record**
(`MemberProfile`) with the member database's columns: MTR ID, name, Gmail, phone,
national ID, birthday, governorate, university, college, major, college ID, graduating
year, guardian's number + kinship, first registration, data confidence and a review note.
A member may or may not have a **portal account**: anyone with a Gmail on the roster gets
one (and signs in with Google), members without one stay **roster-only**; when an account
is later created for an email the roster already knows, it claims that roster row (MTR ID,
participations and dues follow). People edit their own fields from `/profile`.

- **Members page** — searchable/filterable directory, a detail drawer with every event the
  member took part in, inline edit, and **Add member**: the next free MTR ID is filled in
  and a live duplicate check (same name / phone / Gmail) warns before you add someone twice.
- **Participations** — one row per (member × event): role / field, team, mentor, rating,
  registration time. Shown on the member, and on the event card ("Show the N participants").
- **Events** carry the member database's event record too: an Event ID code (`ROV26`),
  level, organizer, location, tracks, result, registered / participant / team counts,
  mentors, captains, contact, recorded budget / spend, funding source, notes. Edit them in
  Data Tables → Events. The curated Hall-of-Fame rosters (team members + awards) are
  separate and unchanged.
- Gated by `members.view` (directory, stats) and `members.edit` (add / edit / remove).

## Finance — the books (`/finance`)

The team's finances, formerly a spreadsheet, as portal tables. Every figure the sheet used
to compute with formulas is computed on read, never stored:

| Tab | What it holds | Computed |
|---|---|---|
| Budget | planned purchases per season / event / subsystem / category, EGP or USD | unit EGP (season USD rate), total & needed qty, FMV, needed cost |
| Spendings | money actually spent, who paid, by which method | net |
| Dues | tiers & loyalty discounts per season, the dues roster, the payments log | maturity (years since first registration), discount, fee, monthly paid grid, expected, balance, projection by segment |
| Funding & payables | grants / sponsors / carry-overs (expected or secured); money owed | — |
| Cash | transfers between holders (blank *from* = opening balance) | balance per holder × method: transfers in − out − fees − spendings paid + dues received |
| Setup | seasons, people & entities (cash holders, suppliers, sponsors), pick-lists | — |

The **Overview** tab is the finance dashboard: still-needed plan, spent, dues collected vs
projected, funding secured, cash on hand and the gap (plan − funding − projected dues), plan
by subsystem, spending against plan by category, money by month, per-season and per-event
roll-ups. Pick-lists (payment methods, categories, sub-categories, subsystems, funding
types, entity types) are data the treasurer edits. Gated by `finance.view` (dashboard) and
`finance.edit` (the editable grids).

## Dashboard (`/explore`) — Board and above

A read-only explorer over all of the portal's data, gated by `dashboard.view` (the Board
preset and above):

- **How it all connects** — every kind of record (members, events, teams, positions,
  inventory, budget, dues, …) laid out by area with its count, and a line for each way one
  kind points at another. Hover to light up a kind's relations, click to browse it.
- **Find anything** — one search box across every kind of record.
- **Any record** — its details, a diagram of what it points to and what points to it, and
  the connected records grouped by kind; click through from one to the next (a "Recently"
  trail leads back). A member also shows what their portal account is part of, and vice
  versa.
- **Charts** — roster, participation and season-finance charts.

Relations come straight from the schema's foreign keys, so new tables appear on their own.
Inside the dashboard each kind of record is still gated by its own domain's view privilege
(`members.view`, `finance.view`, …); tasks, requests and the audit trail are admin-only.

## Data Tables (`/admin/data`)

An inline-editable grid over the portal's tables, grouped by domain — People, Members
(roster), Participations, Org Positions, Event Kinds, Events, Event Categories, Event Teams,
Inventory, every finance table and pick-list (plus read-only views of the rest). Click a
cell, edit, it saves. **Each table is gated by its own privilege** (People needs
`users.manage`, the roster `members.edit`, the books `finance.edit`, …), so the grid never
widens anyone's access. Computed columns are shown read-only. Every table downloads as
`.xlsx`, and an edited file can be uploaded back: the upload previews the diff first
(`apply=false`), then commits; `delete_missing=true` also removes rows you deleted from the
file. The same grid is embedded in the Finance tabs.

### Import components from a file

Inventory managers can bulk-import items from a `.xlsx` / `.csv` (Inventory → **Import**):
preview the detected columns, map them to item fields (name is required;
quantity/category/unit/location/asset-tag/condition optional), optionally dedicate
everything to a team, and import. Re-running upserts (matched by asset tag, then name).

### Moving the member database and books off Google Sheets (one-time)

`backend/scripts/import_member_database.py` loads the two workbooks the team kept in Google
Sheets (download each as `.xlsx`) into the portal — roster, events record, participations,
and the whole finance book. Dry run by default:

```bash
python -m scripts.import_member_database "MTR_Members_Database.xlsx" "MTR_Financial.xlsx"
python -m scripts.import_member_database "MTR_Members_Database.xlsx" "MTR_Financial.xlsx" --commit
```

The sheet is the source of truth for the roster: rows are matched to existing records by
Gmail, then phone, national ID (only when unique) and name; every MTR ID is re-keyed to the
sheet's number; new members with a Gmail get a Google-linked account at the Member level.
Matched events gain their record columns but keep their name, status, kind and awards (the
public Hall of Fame reads those); new events are never created archived, so nothing new
goes public until someone archives it. The finance book loads only into empty books
(`--replace-finance` wipes and reloads). Re-running is safe.

## Quick start

### Option A — Docker (everything at once)

```bash
docker compose up -d --build
```

Builds and starts all three services — Postgres, the backend (migrations + a clean
`app.seed` run automatically before it starts serving), and the frontend (built and
served via nginx, which also reverse-proxies `/api` to the backend so the browser only
ever talks to one origin — same as the Vite dev proxy below, just in production form).

- Frontend: **http://localhost:8080** (`FRONTEND_PORT` to change)
- Backend / API docs: **http://localhost:8000/docs**
- Postgres: **localhost:5432** (portal/portal) — change with `DB_PORT` if that's taken
  (`DB_PORT=5433 docker compose up -d --build`)

Drop a `backend/.env` next to `backend/Dockerfile` before starting (copy it from
`.env.example`) to carry over Google sign-in credentials or
`SEED_ADMIN_EMAIL`/`SEED_ADMIN_PASSWORD` into the containers — `DATABASE_URL` and
`FRONTEND_URL` are always overridden by `docker-compose.yml` regardless, since those two
have to match the container network no matter what's in your local dev `.env`. Set
`SEED_DEMO=1` (in that same `.env`, or `SEED_DEMO=1 docker compose up -d --build`) to load
the sample org instead of the clean one-admin seed.

`docker compose down` stops everything; add `-v` to also drop the Postgres volume (full
reset). Logs: `docker compose logs -f backend` (or `db` / `frontend`).

### Option B — run each piece directly (hot reload, no Docker)

#### 1. Database

```bash
docker compose up -d db        # PostgreSQL 16 on localhost:5432 (portal/portal)
```

No Docker? Set `DATABASE_URL=sqlite:///./portal_dev.db` in `backend/.env` (dev only).

#### 2. Backend

```bash
cd backend
python3.13 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
cp .env.example .env
.venv/bin/alembic upgrade head            # apply migrations
.venv/bin/python -m app.seed              # access ladder + one admin account (real-ready)
.venv/bin/python -m uvicorn app.main:app --reload --port 8000
```

`python -m app.seed` seeds a **clean, real-ready database**: the starting access ladder
plus a single top-level admin login (email/password overridable via `SEED_ADMIN_EMAIL` /
`SEED_ADMIN_PASSWORD`, default `admin@org.local` / `portal123` — change these for a real
deployment). You then add real users, teams, and inventory through the app — nothing is
hardcoded. To load the sample org for exploring/testing instead, run
`python -m app.seed --demo`.

> New migrations must chain onto the current head. Two heads pass CI but abort
> `alembic upgrade head` on deploy — check with `alembic heads` before committing.

#### 3. Frontend

```bash
cd frontend
npm install
npm run dev                   # http://localhost:5173 (proxies /api to :8000)
```

### Default login

The clean seed creates one account — `admin@org.local` (password `portal123`) — the
technical admin, from which you create everyone else in User Management.

### Demo logins (`--demo` only, password: `portal123`)

Running `python -m app.seed --demo` adds a sample org for exploration:

| Email | Level (via personal override) |
|---|---|
| `ceo@org.local` | Board |
| `cto@org.local` | Lead |
| `mech.lead@org.local` | Lead |
| `sw.emp@org.local` | Member |
| `pm@org.local` | Lead |
| `teamlead@org.local` | Lead |
| `student@org.local` | Member |
| `comp@org.local` | *(none — a live "guest" example)* |

Also seeded by `--demo`: `cfo@`, `media@`, `elec.lead@`, `mech.emp@`, `elec.emp@`,
`media.emp@`, `fin.emp@` — all `@org.local` — plus the demo position tree, sample tasks,
a request, and the 100-Arduino inventory example.

## Accounts & sign-in

There are no organization-issued emails — people join with personal addresses:

- **Register** on the login page (name, email, password) — open self-signup, or
- an **admin creates the account** in User Management.

Either way, new accounts start as a **guest** (the ladder's bottom rung, no privileges)
with no hierarchy position: they can sign in but see nothing until someone gives them an
access level (or a seat that carries one) and a manager. Every account gets an empty
MemberProfile roster row on creation. Deactivated accounts are blocked on every sign-in path.

**Google sign-in is a second open-signup path**, same as Register: a verified Google
email with no existing portal account gets a fresh guest account on the spot — same
starting state as registering with a password. `GOOGLE_ALLOWED_DOMAINS`
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

```bash
cd backend
.venv/bin/python -m pytest tests -q
```

246 tests cover the permission layer and every domain: the access ladder (effective level
from seats + override, privilege gating, last-top-override protection), task assignment
(down, up, across, self), subtree visibility and drill-down, request accept/decline/delegate,
status workflow rights (assignee vs. reviewer), hierarchy moves and cycle rejection;
inventory scoping, allocation capacity math, over-allocation/shrink guards, the
who-holds-what breakdown, and the stock-movement ledger with checkout requests
(submit→approve/reject→issue→return, overdue); **event kinds** (admin-addable) with
per-kind automatic roles (a role fires and chains only within its kind, or across all) and
per-kind labels; event nesting with seat-level authority (occupying a role seat whose level
carries `events.manage_seated` manages that event/team — a team role touches only its own
team); file import with upsert; the **Positions** org tree (single root, no
cycles, multi-occupant seats, occupant→manager derivation with vacant-seat skip and
earliest-occupant-wins for shared seats, audit log); user management sourced from a
DB-backed catalog (not a hardcoded frontend list); the general audit log +
soft-delete-by-default with admin-only permanent delete; Google sign-in (auto-provisions a
no-privileges account for any verified email, gated only by the domain allowlist, and
requires an explicit link — never a silent email match — for an email that already has a
password account, with the OAuth round-trip mocked); the **bulk data editor**
(per-table privilege gating, validation, xlsx round-trip, filtered pick-lists, computed
columns); the **finance books** (budget FMV/needed, dues maturity/fees/balances, cash
balances, dashboard roll-up, gating); the **member roster** (roster-only members, MTR IDs,
duplicate check, participations, sign-ups claiming their roster row) and the one-time
**member-database import** (matching, re-keying, Hall-of-Fame fields untouched,
idempotency); the
**dashboard** roll-up and the **calendar** aggregator (per-source privilege skipping,
scope=me vs. general); **time blocks** (span vs. weekday-mask expansion, anchor and manage
rights); the **archive** (open to any member, personalized participation, record editing
gated like reactivation) and the **Hall of Fame** (public PII-free projection, computed
summary counts, in-place record editing); **member profiles** (self-edit vs. managed edit,
unique MTR id); task blocked/comments/history/team-assignment — toggle rights, comment
visibility matching task visibility, the history trail ordering and its
participant-not-admin-only access, multi-assignee batch creation (atomic on a bad assignee,
batch view limited to the assigner), and event-team task scoping; and the generic role-chain
engine — template CRUD/reordering/deletion (with live reparenting and splice-on-delete),
the single ask-once-ever root, a full event→team→member chain seating correctly with
multi-occupant seats, a seat's access level actually gating scoped management, seats starting
vacant, retitle/archive/delete cascading through every level, and never disturbing a real
seat or `manager_id`.

Every test runs with Google OAuth forced to "unconfigured" regardless of what's in
your local `backend/.env` (an autouse fixture in `conftest.py`) — the suite never
depends on real credentials being present or absent on the machine running it.

## Project layout

```
backend/
  app/
    core/                  config, database, security
    domains/
      auth/                sessions, login, Google SSO, current-user deps
      access/              privilege vocabulary + admin-editable access ladder
      users/               accounts, member profiles, admin CRUD
      hierarchy/           recursive-CTE subtree engine + /team views
      tasks/               tasks, workflow, comments, history, attachments
      requests/            up/across requests -> spawned tasks
      notifications/       in-app notifications
      inventory/           items + allocations, capacity, ledger, checkout
                           requests, file import
      events/              events (kind-discriminated) + event record,
                           categories, teams, members, participations,
                           hall_of_fame projection
      members/             the roster: directory, duplicate check, stats
      finance/             the books: budget, spendings, dues, funding,
                           payables, cash — computed views
      positions/           org-chart Position tree, role-chain engine,
                           resync_managers() bridge
      timeblocks/          team calendar blocks (span or weekday mask)
      calendar/            multi-source calendar aggregator
      dashboard/           Home triage roll-up
      archive/             archived events: record + own participation
      public/              unauthenticated, PII-free Hall of Fame for the website
      audit/               general audit log (domain/action/entity, JSON detail)
      bulk/                editable data tables + xlsx round-trip
    seed.py
  alembic/                 migrations
  tests/                   test suite
frontend/
  src/
    api/                   typed REST client
    auth/                  session context
    theme/                 CIRCUIT tokens + AntD theme
    components/            layout, drawers, modals, org tree, calendar,
                           time-block panel, notification bell
    pages/                 Home, Dashboard, Members, Finance, Tasks, Calendar,
                           Inventory, Events, Requests, Team, Archive,
                           Organization, Profile, Admin Users, Audit Log,
                           Data Tables, Login
deploy/                    Caddyfile + production runbook
```

## API surface (all under `/api`)

- `GET /health`
- `POST /auth/login` · `POST /auth/register` · `POST /auth/logout` · `GET /auth/me`
  · `PUT /auth/me/profile` · `POST /auth/change-password` · `GET /auth/config`
  · `GET /auth/google/login` · `GET /auth/google/callback`
- `GET /dashboard` — the Home triage roll-up
- `GET /calendar?scope=&sources=&start=&end=` — tasks | events | inventory | requests | teams
- `GET/POST /timeblocks` · `PATCH/DELETE /timeblocks/{id}`
- `GET/POST /tasks` (`TaskCreate.assignee_ids` — one or more; >1 = a linked team
  assignment) · `GET/PATCH /tasks/{id}` · `PATCH /tasks/{id}/status`
  · `PATCH /tasks/{id}/blocked` · `POST /tasks/{id}/comments`
  · `GET /tasks/{id}/history` · `GET /tasks/batch/{batch_id}` (assigner/admin only)
  · `GET /tasks/team-options` · `POST /tasks/{id}/attachments`
  · `GET /tasks/attachments/{id}`
- `GET/POST /requests` · `POST /requests/{id}/accept` · `POST /requests/{id}/decline`
  (`RequestCreate` accepts an optional `item_id` + `quantity`)
- `GET/POST /inventory` · `GET/PATCH/DELETE /inventory/{id}` — items
  · `GET /inventory/directory` (unscoped id/name/unit, for pickers)
  · `POST /inventory/{id}/allocations` · `POST /inventory/allocations/bulk`
  · `PATCH/DELETE /inventory/allocations/{id}`
  · `GET /inventory/holders`
  · `POST /inventory/import/file/preview` · `POST /inventory/import/file`
  · `GET/POST /inventory/locations` · `DELETE /inventory/locations/{id}`
  · `GET /inventory/{id}/whereabouts` · `GET/POST /inventory/{id}/movements`
  · `GET /inventory/low-stock`
  · `GET/POST /inventory/requests` · `POST /inventory/requests/{id}/approve`
  · `POST /inventory/requests/{id}/reject` · `POST /inventory/requests/{id}/issue`
  · `POST /inventory/requests/{id}/return`
- `GET/POST /events` · `GET/PATCH/DELETE /events/{id}` (nested detail,
  `roles: [{template_id, title, position_id, occupants}]` reflects whatever role
  templates are configured — no `pms`/`lead`/`coach` fields, see `/org/roles` below)
  · `GET/POST /events/kinds` · `PATCH/DELETE /events/kinds/{id}`
  · `POST /events/{id}/categories` · `PATCH/DELETE /events/categories/{id}`
  · `POST /events/categories/{id}/teams` · `PATCH/DELETE /events/teams/{id}`
  · `POST/DELETE/PATCH /events/teams/{id}/members[/{user_id}]`
  · `GET /events/{id}/participations` (`members.view`)
- `GET/POST /members` · `GET/PATCH/DELETE /members/{id}` · `GET /members/stats`
  · `GET /members/next-id` · `POST /members/check-duplicate` — the roster
- `GET /finance/seasons` · `GET /finance/dashboard?season_id=` · `GET /finance/dues?season_id=`
  · `GET /finance/cash` · `GET /finance/events/{id}` — computed views of the books (the
  stored tables are edited through `/bulk`)
- `GET /explore/schema` · `GET /explore/search?q=` · `GET /explore/{table}` ·
  `GET /explore/{table}/{id}` — the data dashboard (`dashboard.view`)
- `GET /archive/events` · `GET /archive/summary` · `GET /archive/events/{id}`
  · `POST /archive/events/{id}/reactivate` · `PATCH /archive/events/{id}`
  · `PATCH /archive/teams/{id}` · `PATCH /archive/members/{id}`
- `GET /public/hall-of-fame` · `GET /public/hall-of-fame/summary` — **unauthenticated**,
  PII-free, for the marketing site
- `GET /org/tree` · `POST /org/positions` · `PATCH/DELETE /org/positions/{id}`
  (`occupant_ids: number[]` — a position can have zero, one, or many occupants)
  · `GET /org/audit`
- `GET/POST /org/roles/templates` · `PATCH/DELETE /org/roles/templates/{id}` — the
  admin-configurable role chain (title template, trigger, order, `access_level_id`,
  optional `event_kind_id`) that auto-seats org-chart positions; zero hardcoded role names
  · `GET /org/roles/root` — whether the single ask-once-ever org-chart root is set
  · `PUT /org/roles/positions/{id}/occupants` — assign who fills a role-chain seat,
  reachable by `org.edit` or by whoever already manages the linked event/team
- `GET /access/privileges` — the fixed privilege vocabulary (keys + labels)
  · `GET /access/levels` (any signed-in user) · `POST /access/levels` ·
  `PATCH/DELETE /access/levels/{id}` (`users.manage`) — CRUD the access ladder
- `GET/POST /users` · `PATCH /users/{id}` (`users.manage`) — accounts, member profile,
  personal level override, manager; the row also reports the person's seats + computed
  effective level
  · `GET /users/assignable` (my subtree) · `GET /users/staff` (request recipients)
  · `GET /users/directory`
- `GET /team` — subtree members with per-status task counts
  · `GET /team/tree` — nested org chart (admin: whole org; others: own subtree)
- `GET /audit` — general audit log (`audit.view`): access changes / inventory quantity / role occupants
- `GET /bulk/tables` · `GET /bulk/{table}` · `POST /bulk/{table}` · `POST /bulk/{table}/validate`
  · `GET /bulk/{table}/export.xlsx` · `POST /bulk/{table}/upload`
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
together from any one of the tasks in the group. A task can also target an **event team**
(`event_team_id` + `team_visible`), which makes it visible to that whole team and lands it
on the team's calendar.

## Deployment

Production runs on an **Oracle VM**, one hop from the browser: Caddy terminates HTTPS on
the VM's own hostname and fronts the same three containers as local Docker
(`docker-compose.yml` + `docker-compose.prod.yml`). Frontend and API are same-origin, so
the session cookie stays first-party.

```bash
export SITE_ADDRESS=portal.mindtechrobotics.com
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

`.github/workflows/ci-cd.yml` is the pipeline: **pytest** and **frontend typecheck/build**
gate every push; on `main` it builds and pushes the backend and frontend images to **GHCR**,
then deploys over SSH by pulling the prebuilt images on the VM and restarting the stack —
nothing is built on the VM. It needs the `VM_*` and Google secrets configured in the repo.

Step-by-step host, DNS, TLS and cutover instructions live in **`deploy/RUNBOOK.md`**;
`DEPLOY.md` documents an older free-tier (Render + Cloudflare Pages) path and is kept for
reference only.
