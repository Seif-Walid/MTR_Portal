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
