"""Seed dev data: roles, the technical admin, one user per role, a multi-role
user (CTO + Software Lead), and a full CEO → PM → Team Lead → Student chain.

Run:  python -m app.seed
Idempotent — safe to re-run. All seeded accounts use password: portal123
"""

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import Base, SessionLocal, engine

# import all model modules so Base.metadata is complete
from app.domains.auth import models as _auth_models  # noqa: F401
from app.domains.notifications import models as _notif_models  # noqa: F401
from app.domains.requests import models as _req_models
from app.domains.tasks import models as _task_models
from app.domains.users import models as _user_models
from app.core.security import hash_password
from app.domains.requests.models import RequestStatus, WorkRequest
from app.domains.tasks.models import Task, TaskPriority, TaskStatus
from app.domains.users.models import NON_STAFF_ROLES, Department, Role, RoleSlug, User, UserRole

DEV_PASSWORD = "portal123"

ROLE_NAMES = {
    RoleSlug.ADMIN: "Technical Admin",
    RoleSlug.CEO: "CEO",
    RoleSlug.CTO: "CTO",
    RoleSlug.CFO: "CFO",
    RoleSlug.SOFTWARE_LEAD: "Software Lead",
    RoleSlug.MECHANICAL_LEAD: "Mechanical Lead",
    RoleSlug.ELECTRICAL_LEAD: "Electrical Lead",
    RoleSlug.MEDIA_MANAGER: "Media Manager",
    RoleSlug.PROJECT_MANAGER: "Project Manager",
    RoleSlug.TEAM_LEAD: "Team Lead",
    RoleSlug.EMPLOYEE: "Employee",
    RoleSlug.STUDENT: "Student",
    RoleSlug.COMPETITION_MEMBER: "Competition Member",
}


def seed_roles(db: Session) -> dict[str, Role]:
    roles: dict[str, Role] = {}
    for slug, name in ROLE_NAMES.items():
        role = db.scalar(select(Role).where(Role.slug == slug))
        if role is None:
            role = Role(slug=slug, name=name, is_staff=slug not in NON_STAFF_ROLES)
            db.add(role)
            db.flush()
        roles[slug] = role
    return roles


def ensure_user(
    db: Session,
    roles: dict[str, Role],
    email: str,
    full_name: str,
    role_slugs: list[RoleSlug],
    manager: User | None = None,
    department: Department | None = None,
) -> User:
    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(
            email=email,
            full_name=full_name,
            hashed_password=hash_password(DEV_PASSWORD),
            department=department,
            manager_id=manager.id if manager else None,
        )
        db.add(user)
        db.flush()
        for slug in role_slugs:
            db.add(UserRole(user_id=user.id, role_id=roles[slug].id))
    return user


def ensure_task(db: Session, assigner: User, assignee: User, title: str, **kw) -> Task:
    task = db.scalar(select(Task).where(Task.title == title))
    if task is None:
        task = Task(
            title=title, assigner_id=assigner.id, assignee_id=assignee.id,
            description=kw.get("description", ""),
            due_date=kw.get("due_date"), priority=kw.get("priority", TaskPriority.MEDIUM),
            category=kw.get("category"), status=kw.get("status", TaskStatus.TODO),
        )
        db.add(task)
        db.flush()
    return task


def run() -> None:
    Base.metadata.create_all(engine)
    db = SessionLocal()
    try:
        roles = seed_roles(db)

        admin = ensure_user(db, roles, "admin@org.local", "Technical Admin", [RoleSlug.ADMIN])
        ceo = ensure_user(db, roles, "ceo@org.local", "Sara Chief", [RoleSlug.CEO])
        # multi-role: CTO + Software Lead in one account
        cto = ensure_user(
            db, roles, "cto@org.local", "Tarek Tech",
            [RoleSlug.CTO, RoleSlug.SOFTWARE_LEAD], manager=ceo, department=Department.SOFTWARE,
        )
        cfo = ensure_user(db, roles, "cfo@org.local", "Farid Finance", [RoleSlug.CFO],
                          manager=ceo, department=Department.FINANCE)
        media_mgr = ensure_user(db, roles, "media@org.local", "Mona Media",
                                [RoleSlug.MEDIA_MANAGER], manager=ceo, department=Department.MEDIA)
        pm = ensure_user(db, roles, "pm@org.local", "Peter Projects",
                         [RoleSlug.PROJECT_MANAGER], manager=ceo)

        mech_lead = ensure_user(db, roles, "mech.lead@org.local", "Malak Mech",
                                [RoleSlug.MECHANICAL_LEAD], manager=cto,
                                department=Department.MECHANICAL)
        elec_lead = ensure_user(db, roles, "elec.lead@org.local", "Eman Electric",
                                [RoleSlug.ELECTRICAL_LEAD], manager=cto,
                                department=Department.ELECTRICAL)

        sw_emp = ensure_user(db, roles, "sw.emp@org.local", "Samir Software",
                             [RoleSlug.EMPLOYEE], manager=cto, department=Department.SOFTWARE)
        mech_emp = ensure_user(db, roles, "mech.emp@org.local", "Mostafa Mechanical",
                               [RoleSlug.EMPLOYEE], manager=mech_lead,
                               department=Department.MECHANICAL)
        ensure_user(db, roles, "elec.emp@org.local", "Esraa Electrical",
                    [RoleSlug.EMPLOYEE], manager=elec_lead, department=Department.ELECTRICAL)
        ensure_user(db, roles, "media.emp@org.local", "Mariam MediaTeam",
                    [RoleSlug.EMPLOYEE], manager=media_mgr, department=Department.MEDIA)
        ensure_user(db, roles, "fin.emp@org.local", "Fatma FinanceTeam",
                    [RoleSlug.EMPLOYEE], manager=cfo, department=Department.FINANCE)

        # full chain: CEO -> PM -> Team Lead -> Student / Competition Member
        team_lead = ensure_user(db, roles, "teamlead@org.local", "Tamer TeamLead",
                                [RoleSlug.TEAM_LEAD], manager=pm)
        student = ensure_user(db, roles, "student@org.local", "Salma Student",
                              [RoleSlug.STUDENT], manager=team_lead)
        ensure_user(db, roles, "comp@org.local", "Karim Competitor",
                    [RoleSlug.COMPETITION_MEMBER], manager=team_lead)

        # sample tasks across the workflow
        soon = date.today() + timedelta(days=7)
        ensure_task(db, ceo, cto, "Quarterly technology roadmap",
                    description="Draft the Q3 technology roadmap for board review.",
                    due_date=soon, priority=TaskPriority.HIGH, category="planning",
                    status=TaskStatus.IN_PROGRESS)
        ensure_task(db, cto, sw_emp, "Fix login page validation",
                    description="Email field accepts invalid addresses.",
                    due_date=soon, priority=TaskPriority.MEDIUM, category="bug",
                    status=TaskStatus.SUBMITTED)
        ensure_task(db, mech_lead, mech_emp, "CAD model for chassis v2",
                    due_date=soon, priority=TaskPriority.URGENT, category="design")
        ensure_task(db, team_lead, student, "Literature review: PID controllers",
                    due_date=soon, priority=TaskPriority.LOW, category="research",
                    status=TaskStatus.APPROVED)

        # a pending request: PM -> CTO (across branches)
        if db.scalar(select(WorkRequest).where(WorkRequest.title == "Need a build server")) is None:
            db.add(WorkRequest(
                requester_id=pm.id, recipient_id=cto.id,
                title="Need a build server",
                description="The competition team needs CI for their firmware.",
                priority=TaskPriority.HIGH, status=RequestStatus.PENDING,
            ))

        db.commit()
        print("Seeded. All accounts use password:", DEV_PASSWORD)
        print("Try: admin@org.local, ceo@org.local, cto@org.local (multi-role), "
              "mech.lead@org.local, sw.emp@org.local, pm@org.local, "
              "teamlead@org.local, student@org.local")
    finally:
        db.close()


if __name__ == "__main__":
    run()
