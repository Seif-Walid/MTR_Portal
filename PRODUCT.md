# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

The primary users are **student members of a competitive university robotics team** (Mind·Tech Robotics, ANU), using the portal alongside their classes. Distinct roles, all held by students:

- **Members** — the bulk of the team (305+ imported from the roster). They receive and work tasks, request inventory, see the org and shared calendar, and appear in the member directory. Baseline "Member" access; a fresh account with no seat is a Guest that sees nothing.
- **Team leads** — run a team/sub-tree: assign tasks down their reporting line, approve inventory requests, manage the events they're seated on.
- **Board / admins** — configure the access ladder, org structure, event kinds, and users; run data sync.

Usage spans desktop and phones; a self-serve Google/Gmail sign-in is the front door.

## Product Purpose

A single internal **operations portal for running the robotics team** — replacing scattered spreadsheets and chats with one system for tasks, physical inventory, events (competitions / training / R&D), the member roster, the org hierarchy and its access control, a shared calendar, and an audit trail. Success is the team coordinating its real work (who does what, who has which parts, what's happening when) without leaving the portal.

## Positioning

What a neighboring ops tool could not truthfully copy is the **data-driven authority model**:

- A **Discord-style access ladder** — privileges are a fixed vocabulary the app can actually gate; levels are admin-editable bundles. There is **no hardcoded role or job title anywhere**.
- **Power comes from org seats**, not names. A person's effective level is the strongest of the seats they occupy plus an optional personal override; building org structure or adding seats never leaks authority by default.
- **Two structural flows on the people tree** (separate from the ladder): tasks flow *down* your recursive subtree; work requests flow *up/across* to people you can't task directly, who accept (spawning a task) or decline.
- **Generic, admin-configurable event kinds and automatic role chains** — Competition/Training/R&D are one entity discriminated by an editable EventKind, with per-kind automatic role seats; nothing about them is special-cased in code.

## Operating Context

- A competitive university robotics team working in **competition seasons** (e.g. MATE ROV, RoboCup, VEX) plus **training** and **R&D** tracks, modeled as Events with nested categories/teams/members.
- **Physical inventory** (real components) tracked across lab locations, with allocations, a movement ledger, and a checkout-request → approve → issue → return flow.
- A **member roster** imported from the org's student-database spreadsheet; members pre-linked to Google so they sign in with their Gmail.
- **Google Workspace/Gmail** is the identity source; **Google Sheets** is an optional external mirror (multi-tab export + destructive rebuild-from-Sheets behind an admin gate).
- Runs as a **Dockerized modular monolith** (FastAPI + SQLAlchemy/Alembic; PostgreSQL in prod, SQLite in dev; React + TypeScript/Vite + Ant Design). New domains (finance) can be added as sibling modules sharing auth/users/permissions.

## Capabilities and Constraints

Confirmed modules: Tasks (assign, blocked state, comments, history, multi-assignee batches), Work Requests, Inventory (items, allocations, locations, movements, checkout requests), Events (Competition/Training/R&D with categories→teams→members and automatic role seats), Members directory (profiles imported from roster), Organization (visual org tree; `manager_id` drives the task/visibility subtree), Access Ladder (privileges + editable levels), Calendar (General vs Me scope across tasks/events/inventory/requests), Audit Log, Notifications, Google sign-in + linking, Google Sheets sync/rebuild, light/dark theme.

Constraints that future work must respect:
- Authority is always derived from seats + the ladder — never hardcode a role, and never let structural edits grant power.
- The people tree (`manager_id`) is the sole source of reporting; visibility and task flow follow it.
- **Arabic / RTL support is a planned requirement.** The UI is currently English while member data is Arabic-name heavy; future design should not assume LTR-only or English-only permanently.
- The dev/prod databases hold **real team data** (roster, inventory) — treated as production truth, not disposable demo data.

Open / undecided: how heavily members use phones vs. desktop (design for both; not yet weighted).

## Brand Commitments

- **Name:** Mind·Tech Robotics. Wordmark renders as `[ MIND·TECH ]` over spaced `ROBOTICS`.
- **Logo:** `frontend/public/logo.png`, rendered via `frontend/src/components/Logo.tsx`.
- **Palette (binding, in `frontend/src/theme/brand.ts`):** black/white dominant with a single red accent — `black #0d0d0e`, `ink #141416` (light-mode primary), `cream #f5f2ea` (dark-mode primary / logo off-white), `paper #faf8f3`, `red #d92d2d`, `siderBg #0c0c0d`. **Red is reserved for accents and danger only.**
- **Light/dark mode** is shipped, persisted per browser, defaulting to OS preference — keep both themes first-class.

## Evidence on Hand

- Real member roster: 305+ students imported from `Members database.xlsx` into the working DB (member profiles: name, MTR id, university/college/major, grad year, contact, etc.).
- Real inventory: 173 real components loaded into the dev DB.
- Real competitions/events and org structure in use.
- Logo asset present; no external marketing assets.
- **No** testimonials, press, customer logos, pricing, or public case studies exist — this is an internal tool; future public surfaces must not fabricate them.

## Product Principles

1. **Authority is data, not code.** Power flows from org seats and the editable access ladder; there are no hardcoded roles, and building structure never leaks power.
2. **Generalize over special-casing.** Multi-kind features (events, role chains) are configured, not hardcoded — expect a generalization pass whenever a "works for my case" feature could serve many.
3. **The people tree is load-bearing.** Reporting, task flow, and visibility all derive from `manager_id`; keep it the single source of hierarchy.
4. **Internal-first, but growing outward.** Primarily internal member/staff ops behind login, with room for public surfaces later (recruitment/apply, sponsor/showcase, public event pages) — design the app so a public layer can be added without contorting it.
5. **Real data is production truth.** The portal carries the team's actual roster and inventory; never wipe or fabricate it.

## Accessibility & Inclusion

- **Arabic / RTL support is a planned requirement**; the member base is Egypt-based and Arabic-first by name. Future work should keep layouts RTL-adaptable and avoid English-only assumptions baked into structure.
- Ship both **light and dark** themes as first-class, contrast-legible in each.
