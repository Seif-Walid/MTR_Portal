"""Test fixtures: in-memory SQLite (recursive CTEs work there too), the full
seed hierarchy, and per-user API clients."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db

# import all model modules so create_all sees every table
from app.domains.audit import models as _audit  # noqa: F401
from app.domains.auth import models as _auth  # noqa: F401
from app.domains.competitions import models as _competitions  # noqa: F401
from app.domains.inventory import models as _inventory  # noqa: F401
from app.domains.notifications import models as _notifications  # noqa: F401
from app.domains.positions import models as _positions  # noqa: F401
from app.domains.requests import models as _requests  # noqa: F401
from app.domains.sync import models as _sync  # noqa: F401
from app.domains.tasks import models as _tasks  # noqa: F401
from app.domains.users import models as _users  # noqa: F401

from app.core.security import hash_password
from app.domains.users.models import NON_STAFF_ROLES, Role, RoleSlug, User, UserRole
from app.main import app

PASSWORD = "testpass123"
_PASSWORD_HASH = hash_password(PASSWORD)  # bcrypt once; reused for all users


@pytest.fixture(autouse=True)
def _isolate_google_settings(monkeypatch):
    """Tests must not depend on whatever Google OAuth credentials happen to
    be in the developer's local backend/.env — default every test to
    unconfigured; test_google_sso.py's own `google_enabled` fixture opts
    individual tests back in via the same monkeypatch mechanism."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "google_client_id", "")
    monkeypatch.setattr(settings, "google_client_secret", "")


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def client(db_session):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def org(db_session):
    """The reference hierarchy:

    ceo
    ├── cto (multi-role: CTO + Software Lead)
    │   ├── sw_emp
    │   ├── mech_lead ── mech_emp
    │   └── elec_lead
    ├── cfo ── fin_emp
    ├── media_mgr
    └── pm ── team_lead ── student, comp_member
    admin (outside the tree)
    """
    db = db_session
    roles: dict[RoleSlug, Role] = {}
    for slug in RoleSlug:
        role = Role(slug=slug, name=slug.replace("_", " ").title(),
                    is_staff=slug not in NON_STAFF_ROLES)
        db.add(role)
        roles[slug] = role
    db.flush()

    def mk(email: str, role_slugs: list[RoleSlug], manager: User | None = None) -> User:
        user = User(
            email=email,
            full_name=email.split("@")[0],
            hashed_password=_PASSWORD_HASH,
            manager_id=manager.id if manager else None,
        )
        db.add(user)
        db.flush()
        for slug in role_slugs:
            db.add(UserRole(user_id=user.id, role_id=roles[slug].id))
        return user

    # .local domain on purpose: the login schema must accept internal domains
    users = {}
    users["admin"] = mk("admin@t.local", [RoleSlug.ADMIN])
    users["ceo"] = mk("ceo@t.local", [RoleSlug.CEO])
    users["cto"] = mk("cto@t.local", [RoleSlug.CTO, RoleSlug.SOFTWARE_LEAD], users["ceo"])
    users["cfo"] = mk("cfo@t.local", [RoleSlug.CFO], users["ceo"])
    users["media_mgr"] = mk("media@t.local", [RoleSlug.MEDIA_MANAGER], users["ceo"])
    users["pm"] = mk("pm@t.local", [RoleSlug.PROJECT_MANAGER], users["ceo"])
    users["sw_emp"] = mk("sw@t.local", [RoleSlug.EMPLOYEE], users["cto"])
    users["mech_lead"] = mk("mlead@t.local", [RoleSlug.MECHANICAL_LEAD], users["cto"])
    users["elec_lead"] = mk("elead@t.local", [RoleSlug.ELECTRICAL_LEAD], users["cto"])
    users["mech_emp"] = mk("memp@t.local", [RoleSlug.EMPLOYEE], users["mech_lead"])
    users["fin_emp"] = mk("fin@t.local", [RoleSlug.EMPLOYEE], users["cfo"])
    users["team_lead"] = mk("tl@t.local", [RoleSlug.TEAM_LEAD], users["pm"])
    users["student"] = mk("stud@t.local", [RoleSlug.STUDENT], users["team_lead"])
    users["comp_member"] = mk("comp@t.local", [RoleSlug.COMPETITION_MEMBER], users["team_lead"])
    db.commit()
    return users


class As:
    """Client wrapper logged in as a given user (own cookie jar per user)."""

    def __init__(self, client: TestClient, email: str):
        self.client = client
        r = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
        assert r.status_code == 200, r.text
        self.cookies = dict(r.cookies)

    def _go(self, method: str, url: str, **kw):
        return self.client.request(method, url, cookies=self.cookies, **kw)

    def get(self, url: str, **kw):
        return self._go("GET", url, **kw)

    def post(self, url: str, **kw):
        return self._go("POST", url, **kw)

    def patch(self, url: str, **kw):
        return self._go("PATCH", url, **kw)

    def put(self, url: str, **kw):
        return self._go("PUT", url, **kw)

    def delete(self, url: str, **kw):
        return self._go("DELETE", url, **kw)


@pytest.fixture()
def login(client, org):
    cache: dict[str, As] = {}

    def _login(who: str) -> As:
        if who not in cache:
            cache[who] = As(client, org[who].email)
        return cache[who]

    return _login


def make_task(login, assigner: str, org, assignee_key: str, title: str = "t") -> dict:
    r = login(assigner).post(
        "/api/tasks", json={"title": title, "assignee_ids": [org[assignee_key].id]}
    )
    assert r.status_code == 201, r.text
    return r.json()[0]


def ensure_position(admin) -> int:
    """A position ID to pass as role_root_position_id — reuses whatever's
    already in the org tree, or creates a root position if there's none yet.
    Competitions/teams/members only need this the very first time any
    role-template position is ever created system-wide; passing it on every
    call is harmless (ignored once the root is already remembered)."""
    tree = admin.get("/api/org/tree").json()
    if tree:
        return tree[0]["id"]
    r = admin.post("/api/org/positions", json={"title": "Org Root"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def setup_role_templates(
    admin, *, pm: bool = False, team_lead: bool = False, member: bool = False
) -> dict[str, int]:
    """Creates the minimal role templates a test needs so competitions/teams
    behave the way they did before role templates existed: a competition-
    scope "PM" template (grants_management + auto_assign_creator, so the
    creator can manage what they just created) and/or a team-scope "Lead"
    template (grants_management, occupancy set explicitly — team creation
    never auto-assigns a manager) and/or a member-scope "Member" template (no
    management implications, just an org-chart seat per roster member).
    Idempotent within a test (checks by event before creating), so callers
    can call this on every _comp()/_team() invocation without creating
    duplicate templates."""
    existing = {t["event"]: t["id"] for t in admin.get("/api/org/roles/templates").json()}
    ids: dict[str, int] = {}

    def _ensure(key: str, event: str, title: str, grants: bool, auto_creator: bool) -> None:
        if event in existing:
            ids[key] = existing[event]
            return
        r = admin.post("/api/org/roles/templates", json={
            "title_template": title, "event": event,
            "grants_management": grants, "auto_assign_creator": auto_creator,
        })
        assert r.status_code == 201, r.text
        ids[key] = r.json()["id"]
        existing[event] = ids[key]

    if pm:
        _ensure("pm", "competition_created", "{competition} PM", True, True)
    if team_lead:
        _ensure("team_lead", "team_created", "{team} Lead", True, False)
    if member:
        _ensure("member", "team_member_added", "{member}", False, False)
    return ids
