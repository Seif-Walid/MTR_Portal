# Decisions

Judgment calls made while building the Mind·Tech Robotics portal, and why. This
tracks deliberate divergences from the canonical spec and the reasoning behind
each, so nothing is a silent surprise.

## Stack

- **FastAPI + SQLAlchemy 2 + Alembic**, not Django + DRF. The portal was built
  incrementally on FastAPI before the canonical spec arrived; the spec is treated
  as a north star for **domain and features**, not a mandate to re-platform.
  Where the spec's stack requirements (Celery/Redis, SimpleJWT, drf-spectacular,
  TanStack Query) are not met, that is a deliberate stack divergence, not an
  oversight.
- **Server-side sessions (httpOnly cookie)**, not JWT. Simpler and adequate for a
  single-origin portal; the security principle the spec cares about — permissions
  resolved server-side, never trusted from the client — holds either way.

## Org tree → Positions (Phase 1)

- The org hierarchy is a tree of **Positions** (title + optional occupant +
  parent), per the spec: a vacant seat still exists. Positions, not people, form
  the structure.
- **Bridge to the existing permission layer:** the tested task/visibility engine
  runs on `users.manager_id`. Rather than rewrite that engine, the Position tree
  **derives** `manager_id`: a position's occupant reports to the occupant of the
  nearest ancestor position that has one. Assigning/moving/vacating a position
  recomputes `manager_id` for the affected occupants. One editable source of
  structure (positions); the permission engine keeps working unchanged.
- **Constraints:** no cycles, a single root, and delete requires the node be a
  leaf (or its children are reparented first) — orphans are blocked, not created.
- **Editable by CEO and Admin only**, reusing the existing org-manager check.
- Every structural change writes an **`OrgAuditLog`** row (actor, action,
  before/after snapshot, timestamp). This also lays the groundwork for the
  versioned "view as of a past date" the spec asks for.

## Competition-scoped roles (Phase 2)

- A competition nests `Competition → Category → Team → TeamMembership`, with one
  or more **Project Managers** per competition.
- **Authority is scoped, not global:**
  - *Create a competition & appoint/remove PMs* — **high staff** (leadership).
    The creator is auto-added as a PM so there's always at least one.
  - *Manage a competition's structure* (categories, teams, appoint team leads) —
    **admin / CEO / a PM of that competition**. High staff are deliberately *not*
    blanket managers of every competition; they get in by being a PM. This keeps
    a person's competition authority tied to that competition, per the spec
    ("a Team Lead in ARL-2026 grants nothing in ARL-2027").
  - *Manage a team's members* — that **team's lead** (scoped, may be a non-staff
    member) *or* anyone who manages the competition.
- The detail endpoint returns `can_manage` (competition) and per-team
  `can_manage_members` for the current user, so the UI shows only the controls
  that will actually work.

## Inventory whereabouts ledger (Phase 3a)

- Physical whereabouts is tracked by an **append-only `StockMovement` ledger**:
  each row moves `quantity` from a source (a `Location`, a holder, or nowhere =
  stock-in) to a destination (a location, a holder, or nowhere = consumed).
  **On-hand is never stored** — it is summed from the ledger, so it always
  reconciles. A move out of a real place is rejected if it exceeds on-hand.
- **Two dimensions, kept separate on purpose:** `Item.quantity` = how many the
  org *owns*; the ledger = *where those units are*. `low_stock_threshold` flags
  scarcity against owned. The earlier purpose-based **allocations** (Holdings
  matrix) remain a third, planning-oriented view; they were not removed because
  they answer a different question ("what is this reserved for") than the ledger
  ("where is it"). A future pass could unify them; for now each lens is useful.
- Phase 3b adds the Request → approve → issue → return flow on top of this
  ledger (issuing an approved request is the only thing that creates the
  issue/return movements — no side-door edits).

## Checkout requests (Phase 3b)

- `InventoryRequest`: item + quantity + reason + needed-by/return-by, states
  `submitted → approved/rejected → issued → returned`. **"Overdue" is a
  computed flag** (`issued` + `return_by` in the past), not a stored state —
  this stack has no background scheduler (already a documented divergence), so
  there is nothing to proactively flip a stored status. A dedicated low-stock
  endpoint and the overdue flag cover the spec's "low-stock thresholds and an
  overdue-return list" without needing one.
- **Approval routes to any inventory manager** (`can_manage_inventory` — staff
  or admin), not a narrower "the item's specific team lead." An item's
  `team_lead_id`, where set, is already a staff-role user by construction (team
  leads hold a staff role in this system), so narrowing further wouldn't change
  who can act — it would just add a rejection path with no security benefit.
  Documented here rather than silently simplified.
- **Issuing an approved request is the only way it creates a `StockMovement`**
  (and returning is the only way that movement reverses) — no endpoint lets
  someone hand-edit whereabouts to fulfill a request. The issuer picks a
  specific location that has enough on hand (`stock.record_movement`'s
  on-hand guard applies here too, so issuing can't oversell a location).
  Returning is allowed by the requester themselves or any inventory manager.

## Attaching an inventory item to a work request

- `WorkRequest` (the general "send a request up/across the hierarchy" flow,
  distinct from `InventoryRequest`'s checkout lifecycle) can optionally carry
  `item_id` + `quantity` — a way to say "I need 5 Arduinos" to someone you
  can't task directly, with a searchable item picker instead of typing it all
  into free text. Quantity is required whenever an item is attached
  (`model_validator` on `RequestCreate`).
- **This is informational only** — it does not create an `InventoryRequest` or
  touch the stock ledger. The recipient sees what's being asked for and
  decides how to fulfill it (including manually starting a real checkout via
  Inventory → Requests). Auto-creating a linked checkout request was
  considered and deliberately skipped: it would mean accepting a work request
  silently commits to a specific fulfillment mechanism, and the two systems
  have different audiences (work requests go to any staff member up/across the
  tree; checkout approval is any inventory manager) — conflating them removes
  a recipient's ability to say "yes, that's approved" without immediately
  deciding logistics.
- The item picker deliberately reads from a new **unscoped** endpoint
  (`GET /inventory/directory` — id/name/unit only, any signed-in user) rather
  than the visibility-scoped `GET /inventory`. A request is precisely the
  mechanism for asking for something outside your normal reach, so scoping the
  picker to what the requester can already see would defeat the purpose.

## Audit log + soft delete (Phase 4)

- **A general `AuditLog`** (domain/action/entity_type/entity_id/detail,
  append-only) covers the spec's three call-outs: permission changes (role,
  manager, active/inactive — `users/router.py`), inventory quantity changes
  (`edit_item`), and competition-role changes (PM add/remove, lead
  assign/clear, member add/remove). Positions already had their own
  `OrgAuditLog` (Phase 1) — left separate rather than merged, since it already
  captures "org structure" with its own before/after shape; the two aren't
  meaningfully more useful combined into one table with a bigger discriminator.
  `GET /audit` is **admin-only** (the spec doesn't say who may view it; admin
  is the safe default for a cross-cutting security/change log).
- **Not logged:** item/competition/team *creation*, allocation and stock-
  movement detail (the movement ledger is already its own append-only audit
  trail — logging it a second time would be redundant), task/work-request
  changes (out of the spec's explicit list for this phase). Could extend later
  if a real need shows up.
- **Soft delete, scoped to what's actually at risk:** `InventoryItem` and
  `CompetitionTeam` get a `deleted_at` column. These were chosen because they
  are the two entities whose FKs currently `ondelete=CASCADE` from
  history-bearing children — a hard delete would silently wipe allocation /
  stock-movement / checkout-request rows (items) or member history (teams).
  `User` already has an equivalent soft-delete via `is_active` (pre-existing,
  not new). `Competition` wasn't given `deleted_at`: allocations already
  `SET NULL` on delete (no cascade risk), and it already has an `archived`
  status plus a "can't delete while referenced" guard — a second soft-delete
  mechanism would be redundant. `CompetitionCategory` and `Position` weren't
  given it either: categories now require their teams be removed first
  (mirrors the leaf-only-delete rule Positions already had), so there's no
  silent cascade to guard against; positions were already leaf-only.
- **Delete endpoints now default to soft delete** (`DELETE .../{id}`, any
  manager) and accept `?permanent=true` for a genuine hard delete, which is
  **admin-only** — matching the spec's "hard delete only for genuine mistakes,
  admin-only" verbatim. A soft-deleted row is invisible everywhere in the
  normal API (list/get/visibility queries all filter `deleted_at IS NULL`);
  there is no "view deleted / restore" UI yet — recovery today means an admin
  querying the DB directly, which is an acceptable gap for a first pass.

## Auth hardening (Phase 5)

- **Google sign-in no longer auto-provisions.** This was a real gap: the
  code's own docstring already claimed "accounts are provisioned by the
  admin... Google is only an authentication method, never a signup path," but
  the implementation directly below it silently created a new `User` on any
  unrecognized-but-verified email. Fixed to match the stated intent (and the
  spec): an unknown email now redirects to `/login?error=no_account` and
  creates nothing. Note this app keeps a **separate, deliberate** open
  self-registration path (`POST /auth/register`, pre-existing) — Phase 5 only
  hardens the *Google* path per the spec's "Google sign-in — specifics"
  section; it doesn't touch that pre-existing password-registration feature.
- **Domain allowlist** (`GOOGLE_ALLOWED_DOMAINS`, comma-separated) is checked
  against the Workspace `hd` claim when present, or the email's own domain
  otherwise (personal Gmail has no `hd`). Empty allowlist = no restriction —
  this org's existing default is open personal-email accounts (see the
  "Accounts & sign-in" section of the README), so the safer-by-default
  posture the spec describes is opt-in via env var here rather than
  hard-locked to a Workspace domain that doesn't exist yet for this org. This
  single mechanism also satisfies the spec's "let personal Gmail in
  deliberately" ask: add `gmail.com` to the same list.
- **Explicit link, not silent match**, implemented without new schema beyond
  one `users.google_linked_at` column: an existing password account's first
  Google sign-in doesn't log the user in — it redirects to
  `link_required`, which tells them to sign in with their password once, then
  use "Link Google account" from the account-menu dropdown. That dropdown
  action re-hits `/google/login` → `/google/callback`; because the browser
  still carries the valid password-session cookie from step one, the callback
  detects it and treats the round-trip as an explicit link (sets
  `google_linked_at`) instead of a sign-in attempt — rather than adding a
  separate "confirm password" form or a new linking endpoint. A Google email
  that doesn't match the currently-signed-in account's email is rejected
  (`google_account_mismatch`) rather than silently switching accounts.
- Service-account credentials for the Sheets mirror remain entirely separate
  from user sign-in credentials (already true before Phase 5 — no change
  needed, just confirming the spec's "do not conflate the two credentials"
  point holds).

### Reversal: Google sign-in now auto-provisions again (post-Phase 7)

The "no auto-provisioning" bullet above was **explicitly reversed** at the
user's direct request ("i want any user to be able to sign in with google
not just pre approved people") — this is a deliberate product decision, not
a bug fix, and directly contradicts the canonical spec's "never
auto-provision with a default role" line. Recorded here so the contradiction
is visible rather than silently overwriting the earlier entry.

- An unrecognized-but-verified Google email now creates a fresh account on
  the spot — same starting state as the pre-existing open
  self-registration path (`POST /auth/register`): **no roles, no manager,
  no permissions** until an admin assigns them via User Management. Google
  sign-in is now simply a second entry point into that same open-signup
  model, not a separate authorization decision.
- `GOOGLE_ALLOWED_DOMAINS` remains the only gate on who this applies to —
  still empty (no restriction) by default, unchanged from Phase 5. If this
  ever needs to be locked down again, that's the existing knob, no new one
  was added.
- Explicit-link-not-silent-match (the OTHER half of Phase 5, for emails
  that already have a *password* account) is untouched — this reversal
  only affects the "no portal account exists yet" branch.
- Frontend's `no_account` error-message mapping (`LoginPage.tsx`) was
  removed as dead code — the backend can no longer produce that error.
- Caught while making this change: the test suite's assumption that Google
  OAuth is "unconfigured by default" silently depended on the developer's
  local `backend/.env` having no real credentials in it — once real
  credentials were added there for live testing, three unrelated tests
  broke because `Settings` reads `.env` at import time regardless of test
  context. Fixed properly rather than worked around: a new autouse fixture
  in `conftest.py` forces `google_client_id`/`google_client_secret` to
  empty for every test by default, so the suite is hermetic regardless of
  what's in anyone's local `.env` going forward.

## Destructive Rebuild-from-Sheets + per-entity export (Phase 6)

- **New `app/domains/sync` domain, separate from the pre-existing inventory
  Sheets mirror.** The inventory-only push (`inventory/sheets.py`) already
  worked and has its own tests/UI; rather than fold it into the new
  multi-tab exporter, the shared low-level client (auth, spreadsheet-open,
  read/write worksheet) was pulled out into `app/core/gsheets.py` and both
  features now depend on it. `inventory/sheets.py` keeps its exact public
  API so its existing tests and the inventory page's "Sync to Sheets" button
  needed zero changes.
- **Ten "structural" tabs, not everything.** The exported/rebuildable set is
  people, positions, competitions, competition_categories, competition_teams,
  competition_pms, competition_team_members, inventory_locations,
  inventory_items, inventory_movements — i.e. the org's reference data.
  Deliberately **out of scope**: tasks, work requests, notifications,
  sessions, inventory allocations/checkout-requests, and both audit logs.
  Those are operational/transactional records generated by day-to-day use of
  the portal, not structural data anyone would maintain in a spreadsheet —
  mirroring them would mean the spreadsheet editor could inadvertently spawn
  or destroy live task/request state. Instead, a rebuild treats them as
  dependent on the structural data and clears/de-references them safely (see
  below) rather than trying to reconcile them against sheet rows.
- **Exact DB-assigned numeric IDs are exported and re-imported as-is**,
  instead of inventing natural keys (e.g. email for people, name+parent for
  positions) for the sheet to key off. This was the single biggest
  simplification in the phase: cross-tab references (a team's `pm_id`, a
  position's `parent_id`, a movement's `item_id`) become plain integer
  lookups validated against an incrementally-built `known_ids` set per tab,
  and self-referential trees (Positions, People via `manager_id`) round-trip
  losslessly. The tradeoff is that the sheet is not meant to be hand-typed
  from scratch — it's meant to be edited starting from an export — which
  matches how the feature is actually used (export, edit in the spreadsheet,
  rebuild).
- **Rebuild is validate-then-commit, never partial.** `dry-run` parses and
  cross-validates every tab and returns counts + a full error list with zero
  DB writes; `commit` re-validates (never trusts a stale dry-run result) and
  refuses to touch the database at all if any error exists. There is no
  partial-import / best-effort mode — a sheet with one bad row imports
  nothing, by design, since a half-applied structural rebuild would be worse
  than no rebuild.
- **Snapshot-to-JSON before touching anything, not `pg_dump`/file-copy.**
  `DATABASE_URL` can point at SQLite locally or Postgres in production, so a
  portable dump of every managed table's current rows to a timestamped JSON
  file (`backend/snapshots/`, gitignored — same reasoning as `.env`, this can
  contain real org data) works identically on either engine and needs no
  extra tooling. It's a recovery artifact, not a restore feature — restoring
  from it today is a manual DB operation, matching the same "acceptable gap
  for a first pass" judgment made for soft-delete restore in Phase 4.
- **Dependent tables are cleared, not left dangling, before the truncate.**
  Tasks/requests/notifications/sessions/allocations/checkout-requests are
  deleted outright (they reference people/items that are about to disappear
  and have no meaning without them); `OrgAuditLog`/`GeneralAuditLog` rows are
  kept but have `actor_id` set to NULL rather than being deleted, since the
  log entries themselves ("position X was edited") are still historically
  true even once the actor who did it is gone. All *sessions* are cleared
  unconditionally, including the acting admin's own — a rebuild invalidates
  every `user.id` in existence and reissues them, so there's no safe way to
  keep any session alive through it; the acting admin will need to sign back
  in immediately after, which the frontend surfaces as an expected outcome
  ("Everyone will need to sign in again afterward" in the confirmation
  modal) rather than a bug.
- **Rebuilt user rows get an intentionally-unusable password hash**
  (`hash_password("rebuild-" + id + "-" + timestamp)`), not a random one that
  someone might try to brute-force or a blank one that could be mistaken for
  "no password set." Nobody can log in with a password after a rebuild until
  they either use Google sign-in (if their email matches and is allowed) or
  go through the normal "forgot password" flow — this was chosen over trying
  to preserve/re-import password hashes because the spreadsheet has no safe
  way to carry a hash without exposing it to anyone with sheet access.
- **Commit is gated to `is_admin or is_ceo` specifically — one step stricter
  than the general "org manager" gate used for export/dry-run/history.**
  Export and dry-run are read-only or additive-only (dry-run touches
  nothing; export only pushes current DB state outward) so the existing
  org-manager circle (admin + CEO by role) can use them freely. Commit is the
  only endpoint that can destroy data org-wide, so it's narrowed further to
  literally the two roles the canonical spec calls "irreversible, admin/CEO
  only" for. On top of the role gate, `confirm_phrase` must exactly equal
  `settings.org_name` (`"Mind-Tech Robotics"`, configurable per deployment) —
  a typed confirmation rather than a checkbox, so the action can't be
  triggered by a stray click.
- **No async task queue for exports** (same divergence as every other phase
  that touches Sheets): `export_all()` runs synchronously inside the request.
  Ten tabs against the Sheets API is a few seconds at most, and this stack
  has no Celery/Redis by design (see the running "no async task queue" note
  from earlier phases) — a background job here would be new infrastructure
  for a rare, admin-only, already-fast operation.

## Tasks: blocked state, comments, history, team assignment (Phase 7)

- **"Team assignment" means bulk-assigning one task template to several
  people, not a new Team entity or a single shared-status task.** This was a
  genuine fork with real tradeoffs (asked the user directly rather than
  guessing): a `CompetitionTeam`-based assignment would need a new
  shared-status concept (what does "in progress" mean if one of five members
  started?), and a standalone Team model would be the biggest addition for
  the least reuse of what already exists. Instead, `TaskCreate.assignee_ids`
  accepts one or more IDs; the backend creates one fully independent `Task`
  row per person (each moves through the existing single-assignee workflow
  untouched), and when there's more than one, they share a `batch_id` (a
  bare `uuid4().hex`, no new table) purely so the assigner can see the
  group's progress together via `GET /tasks/batch/{id}`. A single-assignee
  task gets `batch_id = null` — it's indistinguishable from a task created
  before this phase existed.
- **Batch creation is all-or-nothing.** Every assignee in the list is
  validated against `can_assign_task` *before* any `Task` row is created; a
  bad name anywhere in the list means nothing is created, rather than
  silently assigning to the valid subset. A half-delivered team assignment
  (some people notified, some not) would be worse than a clear rejection.
- **`GET /tasks/batch/{id}` is assigner-only (or admin), not everyone in the
  batch.** Any single assignee can already see their own task; seeing every
  other assignee's status side-by-side is a manager's view of the group,
  not something a peer needs by default.
- **Blocked is a flag on top of status, not a new status value.** A task can
  be blocked while `todo` or `in_progress` — it's "I'm stuck," not a forward
  workflow step like `submitted`/`approved`, so folding it into the
  `TRANSITIONS` state machine would have meant blocking (and un-blocking)
  from every status, doubling the transition table for no workflow benefit.
  `is_blocked` + `blocked_reason` toggle independently of `status` instead.
  Toggle rights: assignee, assigner, or admin — deliberately more permissive
  than status transitions (which are strictly assignee-only or
  reviewer-only), because "we're stuck" is information either side of a
  task should be able to raise or clear, not an authority to gate.
- **Comments are open to anyone who can already view the task** — no
  narrower permission than that. The alternative (assigner/assignee only)
  would have hidden comments from exactly the people the existing visibility
  rule already trusts to see the task (a subtree manager, or a requester
  whose request spawned it) — comments are lower-stakes than a status change
  or a blocked-flag, so they don't need a stricter gate.
- **History reuses the Phase 4 general `AuditLog` table** (`domain="tasks"`)
  rather than a task-specific log table — `created`, `status_changed`,
  `edited`, `blocked`/`unblocked` all write through the same `audit_log()`
  helper already used by inventory and competitions. The *access* pattern is
  new, though: `GET /tasks/{id}/history` is gated by task visibility
  (`can_view_task`), not `is_admin` like the general `/audit` endpoint —
  a task's own participants need to see its trail without being admins,
  and this doesn't weaken the general audit log's admin-only guarantee
  since it's a separate endpoint reading the same table.
- **Task creation via the Requests domain (`accept_request`) is untouched**
  — it builds a `Task` directly and was already working before this phase;
  wiring it into the same `created` audit entry as `tasks/router.py` would
  have been a small addition but is out of the four things this phase
  actually asked for, so it was left alone. Its tasks simply won't show a
  "created" history entry, only whatever happens to them afterward.
- **SQLite gotcha, recurring pattern**: adding `is_blocked`/`blocked_reason`
  as `NOT NULL` columns to the *existing* `tasks` table (which can already
  have rows) fails on SQLite without an explicit `server_default` — verified
  by hand (inserted a raw pre-migration row, then ran the autogenerated
  migration unmodified: `Cannot add a NOT NULL column with default value
  NULL`). Fixed by adding `server_default` to both columns, then dropping it
  again in the same migration once the backfill is done, so future inserts
  rely on the ORM-side default like the rest of the schema. `task_comments`
  and `batch_id` needed no such fix (new table; nullable column).

## Dockerizing the whole stack, not just Postgres

The spec's deliverable is "Running `docker compose up` gives Postgres +
backend + frontend" — until now only Postgres was containerized (the
original `docker-compose.yml`), with backend/frontend expected to run via a
local Python venv / Node install. Added `backend/Dockerfile`,
`frontend/Dockerfile` + `nginx.conf`, and two more services in
`docker-compose.yml`, actually built and run end-to-end against real
Postgres (not just eyeballed) to verify this.

- **Frontend is a real build, served by nginx — not the Vite dev server in
  a container.** Multi-stage Dockerfile: `node:20-alpine` builds
  (`npm run build`, which already runs `tsc --noEmit` first — a broken
  build fails the image, not just a lint warning), then `nginx:alpine`
  serves the static output. `nginx.conf` reverse-proxies `/api/` to the
  `backend` service and falls back to `index.html` for every other path
  (React Router). This preserves the existing "same-origin, no CORS
  needed" architecture that the Vite dev proxy already relies on
  (`vite.config.ts`'s own comment: *"same-origin in dev: session cookie
  just works"*) — the browser only ever talks to one origin either way.
- **Backend seeds itself on every start, idempotently** —
  `docker-entrypoint.sh` runs `alembic upgrade head` then
  `python -m app.seed` (both already safe to re-run: migrations are
  no-ops once applied, and `seed_roles`/`seed_admin` check-then-create)
  before exec-ing uvicorn. `SEED_DEMO=1` opts into `--demo` instead,
  matching the existing non-Docker convention exactly rather than
  inventing a separate Docker-only seeding story. No new "is this a fresh
  DB" branching logic needed — the existing idempotency already covers it.
- **Backend picks up `backend/.env` if present, but two values always win.**
  `env_file: backend/.env` (marked `required: false` so a fresh clone with
  no `.env` yet still starts) carries over anything optional — Google/Sheets
  credentials, `ORG_NAME`, `SEED_ADMIN_*` — into the container for free,
  since `environment:` in Compose overrides `env_file:` values.
  `DATABASE_URL` and `FRONTEND_URL` are set directly in `environment:`
  regardless of what a local dev `.env` says (it likely points at
  `sqlite:///...` and `localhost:5173`), because those two must match the
  container network topology (`db` service hostname; the frontend's
  Docker-exposed port) no matter what.
- **A real, previously-undiscovered SQLite/Postgres portability bug** was
  caught building this: Phase 7's migration
  (`689a99d163d0_task_blocked_state_comments_batch_.py`) used
  `server_default=sa.text('0')` for a new `Boolean` column, which SQLite
  tolerates (loose integer/boolean coercion) but Postgres rejects outright
  (`column "is_blocked" is of type boolean but default expression is of
  type integer`). Fixed with `sa.false()`, which SQLAlchemy renders
  correctly per-dialect. This was only caught because dockerizing forced an
  actual migration run against real Postgres — **the pytest suite has never
  once run against Postgres**; `tests/conftest.py`'s `db_session` fixture
  hardcodes `sqlite://` directly, ignoring `DATABASE_URL` entirely, so 139
  passing tests only ever proved SQLite compatibility. Worth knowing: this
  bug (and any other latent dialect difference across all 7 phases) could
  not have been caught by the existing test suite as it stands today — it
  was caught by hand-verifying the dockerized stack against Postgres this
  session, not by CI. Making the test suite dialect-parametrizable is a
  reasonable follow-up if Postgres parity ever needs to be continuously
  guaranteed rather than spot-checked.
- **Startup-order hardening**: `docker-entrypoint.sh` retries
  `alembic upgrade head` a few times with a short sleep before giving up.
  `depends_on: condition: service_healthy` only guarantees Postgres passed
  its own `pg_isready` check — it doesn't guarantee the Docker network's
  embedded DNS has fully propagated the new `backend` container's
  resolution of the `db` hostname in the same instant everything starts
  together, which caused one transient failure while verifying this
  end-to-end. A bare `depends_on` was not enough on its own in practice.
- **Postgres's host port is now `${DB_PORT:-5432}`** (was hardcoded
  `5432:5432`) — found this the hard way when the verification host already
  had a native Postgres bound to 5432, unrelated to Docker. The backend's
  own port (8000) was left fixed, since `GOOGLE_REDIRECT_URI`'s default is
  already hardcoded to that port and there was no live collision to justify
  the extra indirection.

## Generic, admin-configurable role chains (org positions <-> competitions)

First cut of this feature (see git history of this file if ever needed)
hardcoded three roles — PM, Team Lead, Coach — as a Python enum, one occupant
each. Feedback after using it: real roles aren't always one-person (a
competition can have several PMs, "Team Member" is the whole roster), and
hardcoding role *names* in code at all defeats the point — adding "Assistant
Coach" later should be a config change on the site, never a code change.
Rebuilt around two ideas: **positions can have any number of occupants**, and
**roles are admin-defined data, not Python constants**.

- **`Position.occupant_id` (single FK) became a join table,
  `PositionOccupant`.** Every position — a real seat like "CEO" or a role-
  chain seat — uses the same list-of-occupants concept; nothing stops a real
  seat from having co-occupants either, it's just not the common case.
  `resync_managers()` and `clear_user_from_other_positions()` were adapted
  to operate on lists: when a parent position has more than one occupant,
  `manager_id` derivation picks the earliest-added one (same "earliest wins"
  convention now used everywhere multiplicity needs to collapse to one).
- **`RoleTemplate`** (`app/domains/positions/models.py`) replaces the old
  `AutoPositionKind` enum entirely: `title_template` (with `{competition}`/
  `{team}`/`{member}` placeholders), `event` (one of the three fixed trigger
  points the app actually has — `competition_created`, `team_created`,
  `team_member_added` — not a role name, just the app's fixed structure),
  `sort_order` (globally unique, defines a single linear chain), and two
  booleans: `grants_management` (occupying this seat confers the same
  authority a competition PM/team lead used to) and `auto_assign_creator`
  (whoever creates the competition/team is auto-seated here — this is what
  keeps "create a competition and you're its PM" working without hardcoding
  which role that is). Admins manage the whole list from a panel on the
  Organization page — create, reorder, delete, no code involved, ever.
- **Only the very first role-template position, ever, asks where it goes.**
  Every later one — regardless of kind — chains under whichever earlier-
  order template already has a position for an ancestor entity (competition
  -> team -> membership), walking backward through the configured order.
  This replaced the first draft's "ask once *per kind*" (three separate
  prompts) — the user's own feedback was that one role should be able to be
  "the boss of" another, i.e. one connected chain, not three parallel asks.
- **`CompetitionPM`, `CompetitionTeam.lead_id`/`coach_id` are gone
  entirely** — replaced by role-template positions with
  `grants_management=true`. "Who can manage this competition" is now
  `admin OR ceo OR occupies a grants_management position for it`
  (`competitions/service.py::can_manage_entity` bridges the generic
  occupant-editing endpoint back to this domain's competition ->  team ->
  membership authority-escalation rules, since the generic
  `positions` domain doesn't know that shape). A consequence worth
  flagging: since occupancy is now the *only* source of authority, archiving
  a competition (which removes its role positions from the org chart —
  see the "Archiving removes role positions" addendum below) leaves its own
  PM locked out of managing it until someone (admin/CEO, or the PM once
  re-appointed) reactivates and re-seats them — there's no "remembered
  occupant" restored automatically the way the old `CompetitionPM`-derived
  seat used to resync itself.
- **A team's whole roster gets seated too** — something the first draft
  didn't support at all, since one-occupant-per-position made a "Team
  Member" role structurally impossible. Adding a member fires
  `team_member_added`; any role template on that event auto-occupies with
  the person just added (the event itself identifies who — no manual pick
  needed, unlike every other scope).
- **Reordering or deleting a role template live-updates every already-
  seated position.** `competitions/role_sync.py::resync_all()` walks every
  competition -> team -> membership and re-derives each existing position's
  parent from the current chain — deleting a template from the middle
  splices it out (whatever was chained under it reattaches to whatever's
  now above it) rather than orphaning anything.
- **Bug found while building this: renumbering `sort_order` via a direct
  swap collides with its own unique constraint.** Swapping two templates'
  order (`UPDATE role_templates SET sort_order=? WHERE id=?` twice) can hit
  SQLAlchemy's insertmany/executemany batching in an order where both rows
  briefly want the same value before the other's update lands, tripping the
  unique constraint mid-flush. Fixed with a two-phase renumber: stage every
  affected row to a negative placeholder first, flush, then assign the real
  1..N values — the general pattern for "renumbering a uniquely-constrained
  sequence" any time it recurs elsewhere.
- **Bug found while building this: two relationships, one underlying table,
  one goes stale.** `Position.occupants` (a `secondary=` viewonly join to
  `PositionOccupant`) and `Position.occupant_links` (the actual owned,
  cascade-managed collection) both read the same rows, but SQLAlchemy caches
  them independently. Deleting through `occupant_links` (as
  `vacate_positions_for_entity` originally did) left the *other*
  relationship — the one the API schemas actually serialize — still
  reporting the old occupant. Same root cause as the `occupant`/`occupant_id`
  staleness bug from the first draft of this feature, recurring in a new
  shape: fixed by explicitly `db.expire(pos, ["occupants", "occupant_links"])`
  after every mutation, not just the one relationship that was directly
  written through.
- **A real, near-miss data-loss bug in the migration, caught before it
  shipped.** The migration that dropped the old single `occupant_id` column
  did so *before* copying its values into the new `PositionOccupant` table —
  a straight `drop_column` that would have silently destroyed every real
  seat assignment in the database, including the one actually in use on the
  dev DB (confirmed via `org_audit_log`, then restored by hand). Fixed by
  inserting a data-carry-forward step (`INSERT INTO position_occupants
  SELECT id, occupant_id, now() FROM positions WHERE occupant_id IS NOT
  NULL`) before the column drop, with the same treatment in `downgrade()`
  carrying the earliest occupant back the other way. Re-verified against
  both SQLite and a throwaway Postgres container with real seeded occupant
  data surviving both directions before trusting it again. Worth
  remembering generally: a migration that *replaces* a column's storage
  shape, not just adds/drops unrelated ones, needs an explicit data-carry
  step and a from-real-data test — "the migration ran without error" and
  "the migration preserved data" are different claims.

### Phase 5: one add flow, and a chain-break rule instead of a fixed-parent field

First cut of this addition gave `RoleTemplate` a `fixed_parent_position_id`
column so a role could skip the chain and always parent under one explicitly
chosen position ("non-chaining"), with a second, tree-anchored add flow to
set it. Feedback: "i believe you might have overcomplicated things" — the
actual ask was simpler: add a role from the same "Add position" flow used
everywhere else (a `Switch` in `PositionModal`, `frontend/src/pages/
OrganizationPage.tsx`, toggling between the normal Title/Occupants/Technical
fields and the role's Title/When/checkboxes fields), and let the *existing*
event-based chain already imply "non-chaining" without a new field at all.
Reverted the column/migration entirely (never shipped, so a clean revert —
downgrade the dev DB off it, delete the migration file, drop the field) and
replaced it with a rule in `_find_chain_parent`
(`app/domains/positions/role_engine.py`):

- Templates sharing the same `event` naturally chain together in
  `sort_order` — unchanged from Phase 4.
- A template with nothing earlier in `sort_order` that could ever apply to
  its own lineage resolves straight to the shared root, same as before —
  this is what makes a role "non-chaining" for free: give it a `sort_order`
  with no eligible prerequisite and it always sits at the top.
- **New:** a template *is* eligible (some earlier template's event produces
  an entity type present in this lineage) but none of those earlier
  templates have actually produced a position for it yet — the chain has a
  missing link — the template is skipped entirely, not orphaned under root.
  This surfaces a real, previously-unhandled gap: `apply_event` only ever
  fires at creation time, so a template added *after* some competitions/
  teams already exist is never backfilled onto them; anything that would
  have chained under it for those older entities now correctly waits
  instead of popping up disconnected at the top of the tree. Covered by
  `test_template_added_after_entity_exists_blocks_dependents_instead_of_orphaning_to_root`
  in `backend/tests/test_role_engine.py`.
- `resync_position_parent` gets the same treatment: a position whose chain
  link is now missing (e.g. after a reorder/delete elsewhere) is left
  exactly where it last resolved rather than deleted or reparented — this
  function only ever re-derives *existing* positions, it doesn't remove
  seats a real person may be occupying just because a chain above them
  broke.

### Phase 5b: one tree, templates shown where they'd chain, hidden by default

Feedback on the switch-in-`PositionModal` UI itself: "look again with the over
complication... in org there is only 1 tab i suggust you make a switch that
shows automatic roles but by default they are hidden... if i flip the main
switch i will see ceo ->{competition} pm where i can add a role under comp
pm." The separate "Automatic roles" list panel (an ordered list with up/down
arrows, disconnected from the position tree) was removed entirely. In its
place:

- A new, purely structural helper, `role_engine.template_chain_parent_id`,
  answers "which other template would this one nest under" using the same
  backward-search shape as `_find_chain_parent`, but against a fixed
  structural lineage (`competition_created` -> `{"competition"}`,
  `team_created` -> `{"competition", "team"}`, `team_member_added` ->
  `{"competition", "team", "membership"}`) instead of a real entity's actual
  lineage — no positions need to exist yet for this to answer correctly,
  which is what lets the org tree preview the whole chain before a single
  competition/team has ever been created. Exposed as `parent_template_id` on
  `RoleTemplateOut`, computed by the router on every list/create/edit call.
- `OrganizationPage.tsx` merges role templates into the *same* `Tree` as real
  positions: a template with `parent_template_id: null` renders nested under
  the org's top real position (matching the user's own "ceo -> {competition}
  pm" example); a template with a parent renders nested under that parent
  template's own node. A page-level `Switch` ("Show automatic roles",
  default off) controls whether these placeholder nodes appear at all —
  hidden by default, matching the ask.
- Adding a role from a placeholder node's own "+" (as opposed to `+` under a
  real position) skips the "When" dropdown entirely and silently inherits
  the clicked placeholder's `event` — per explicit user clarification ("it
  becomes automatic with the same condition"). This isn't just a UX
  shortcut: since the new template's `sort_order` is always appended at the
  end, inheriting the *same* event as the immediate parent is what
  guarantees the structural walk actually resolves back to that exact node,
  rather than possibly skipping past it to some other eligible template.
- Reordering moved from up/down buttons to dragging a template node onto
  another template node in the tree (`onDrop` branches on a `tpl-` key
  prefix vs. a plain position id, computing a target rank from the drop
  position and calling the same `PATCH .../templates/{id}` endpoint that
  already existed for this).
- **Bug found while building this:** antd's `Tree` `defaultExpandAll` only
  applies once, at mount. CEO had zero children when the page first loaded
  (before any template existed), so when a template was later added and the
  "Show automatic roles" switch flipped on, the newly-added child never
  appeared — the tree's internal expanded-keys state had already been fixed
  at "nothing to expand" and doesn't recompute just because `treeData`
  grows. Fixed by switching to a controlled `expandedKeys` state,
  recomputed (to "every key currently in `treeData`") via a `useEffect` on
  `treeData` itself, with `onExpand` still wired so a user's manual collapse
  during their session is respected until the next structural change.
  General lesson: a tree component with `defaultExpandAll`-style
  mount-only props needs a controlled equivalent the moment the tree's
  *shape* (not just node content) can change after mount.

First cut of the "+" on a placeholder used a stripped-down modal (title +
checkboxes only, event silently inherited, no switch). Feedback: "what is so
hard it should look like a normal role and can be automatic itself maybe i
want to add a diffrent condition." So it's now the *same* modal shape as
everywhere else:

- Switch off (default): just a Title, with a caption saying it appears under
  the clicked role with the same condition — this is the "normal role under
  an automatic one" case (a plain "Team Lead" that materializes under each
  team's Coach), which is still a template under the hood since a real
  position can't hang off an abstract placeholder.
- Switch on: the full role form including a "When" select, pre-filled with
  the parent's condition but changeable — e.g. under "{competition} PM" add
  "{team} Coach" firing on team creation. The options are filtered to
  conditions at least as deep as the parent's (competition -> team ->
  membership): a competition-level role structurally can't nest under a
  team-level one (no team exists when a competition is created), so
  shallower conditions aren't offered.
- Backing both: `RoleTemplateCreate.insert_after_id` — a template added from
  a placeholder's "+" is inserted into the chain *immediately after* that
  template rather than appended at the end. This also fixed a latent
  mis-nesting: appending meant a role added "under PM" would actually chain
  under whatever same-event template happened to be last (e.g. Deputy PM),
  not the node the admin clicked. Covered by
  `test_insert_after_nests_new_role_under_the_clicked_parent`.

### Archiving removes role positions (was: vacates)

Phase 4 originally had archiving a competition (and soft-deleting a team)
*vacate* its role positions — the seats stayed in the org chart, empty, on
the theory that the entity is still queryable so its structure should be
too. Changed on direct request ("make sure that archiving a competition also
removes the roles", echoing the original "when archived/deleted the roles
are deleted from the org"): the org chart only shows active work.

- Archiving a competition now hard-deletes every role position it produced,
  at every level (competition, team, membership). Soft-deleting a team does
  the same for its subtree — the team *row* is what stays queryable as
  history, not its seats.
- Reactivating an archived competition rebuilds the whole role structure
  from whatever templates exist at that moment (same `apply_event` path as
  creation, walking competition -> teams -> memberships, skipping
  soft-deleted teams). Seats come back vacant — occupancy is not remembered
  — except member seats, which the membership itself re-fills. So a PM
  stays locked out after an archive/reactivate round-trip until re-appointed
  (admin/CEO can always act), same authority consequence as before, reached
  by removal instead of vacating.
- `vacate_positions_for_entity` lost its last caller and was deleted from
  `role_engine.py`.
