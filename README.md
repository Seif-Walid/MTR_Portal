# Mind·Tech Robotics — Operations Portal

Standalone internal portal: task management, org-hierarchy-based access control, and
per-role dashboards. Modular monolith designed so **inventory** and **finance** modules
can be added later as sibling domains sharing auth, users, and the permission layer.

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

Moving a person in the tree (admin → User Management → "Reports to") instantly changes
who can see and task them. No code or permission changes. All rules are enforced
server-side in the API; the UI only hides what the API already forbids.

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
.venv\Scripts\python -m app.seed          # seed roles + demo org
.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000
```

### 3. Frontend

```powershell
cd frontend
npm install
npm run dev                   # http://localhost:5173 (proxies /api to :8000)
```

### Seeded logins (password: `portal123`)

| Email | Who |
|---|---|
| `admin@org.local` | Technical admin (user management) |
| `ceo@org.local` | CEO — sees everything |
| `cto@org.local` | **Multi-role**: CTO + Software Lead |
| `mech.lead@org.local` | Mechanical Lead |
| `sw.emp@org.local` | Software employee (leaf) |
| `pm@org.local` | Project Manager |
| `teamlead@org.local` | Team Lead (under PM) |
| `student@org.local` | Student (under Team Lead) |

Also seeded: `cfo@`, `media@`, `elec.lead@`, `mech.emp@`, `elec.emp@`, `media.emp@`,
`fin.emp@`, `comp@` — all `@org.local`.

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

32 tests cover the permission layer: assignment allowed/denied (down, up, across,
self), subtree visibility and drill-down, request accept/decline/delegate, status
workflow rights (assignee vs. reviewer), multi-role union, hierarchy moves and
cycle rejection.

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
      (inventory/)         future module — same pattern
      (finance/)           future module — same pattern
    seed.py
  alembic/                 migrations
  tests/                   permission-layer test suite
frontend/
  src/
    api/                   typed REST client
    auth/                  session context
    components/            layout, task drawer, modals, notification bell
    pages/                 Tasks, Requests, Team, Admin Users, Login
```

## API surface (all under `/api`)

- `POST /auth/login` · `POST /auth/logout` · `GET /auth/me`
- `GET/POST /tasks` · `GET/PATCH /tasks/{id}` · `PATCH /tasks/{id}/status`
  · `POST /tasks/{id}/attachments` · `GET /tasks/attachments/{id}`
- `GET/POST /requests` · `POST /requests/{id}/accept` · `POST /requests/{id}/decline`
- `GET /team` — subtree members with per-status task counts
- `GET /users/assignable` (my subtree) · `GET /users/staff` (request recipients)
- `GET/POST/PATCH /users` — admin only
- `GET /notifications` · `GET /notifications/unread-count` · `POST /notifications/mark-read`

Interactive docs: http://localhost:8000/docs

## Task workflow

`To Do → In Progress → Submitted for Review → Approved / Revision Requested`

The assignee drives progress; only the assigner **or anyone above the assigner** can
approve or request revision. Every assignment, status change, and request resolution
produces an in-app notification.
