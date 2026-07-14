"""Test fixtures: in-memory SQLite (recursive CTEs work there too), the full
seed hierarchy, and per-user API clients."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db

# import all model modules so create_all sees every table
from app.domains.auth import models as _auth  # noqa: F401
from app.domains.notifications import models as _notifications  # noqa: F401
from app.domains.requests import models as _requests  # noqa: F401
from app.domains.tasks import models as _tasks  # noqa: F401
from app.domains.users import models as _users  # noqa: F401

from app.core.security import hash_password
from app.domains.users.models import NON_STAFF_ROLES, Role, RoleSlug, User, UserRole
from app.main import app

PASSWORD = "testpass123"
_PASSWORD_HASH = hash_password(PASSWORD)  # bcrypt once; reused for all users


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
        "/api/tasks", json={"title": title, "assignee_id": org[assignee_key].id}
    )
    assert r.status_code == 201, r.text
    return r.json()
