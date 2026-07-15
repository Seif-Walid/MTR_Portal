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
