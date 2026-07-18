"""Seed dev data: roles, the technical admin, one user per role, a multi-role
user (CTO + Software Lead), and a full CEO → PM → Team Lead → Student chain.

Run:  python -m app.seed
Idempotent — safe to re-run. All seeded accounts use password: portal123
"""

import os
import sys
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import Base, SessionLocal, engine

# import all model modules so Base.metadata is complete
from app.domains.audit import models as _audit_models  # noqa: F401
from app.domains.auth import models as _auth_models  # noqa: F401
from app.domains.competitions import models as _comp_models  # noqa: F401
from app.domains.inventory import models as _inv_models  # noqa: F401
from app.domains.positions import models as _pos_models  # noqa: F401
from app.domains.notifications import models as _notif_models  # noqa: F401
from app.domains.requests import models as _req_models
from app.domains.tasks import models as _task_models
from app.domains.users import models as _user_models
from app.core.security import hash_password
from app.domains.competitions.models import (
    Competition,
    CompetitionCategory,
    CompetitionStatus,
    CompetitionTeam,
    CompetitionTeamMember,
)
from app.domains.inventory.models import (
    AllocationPurpose,
    Condition,
    InventoryAllocation,
    InventoryItem,
    InventoryRequest,
    InventoryRequestStatus,
    Location,
    StockMovement,
)
from app.domains.inventory.stock import record_movement
from app.domains.positions.models import Position, PositionOccupant
from app.domains.positions.service import resync_managers
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


def seed_inventory(db: Session, team_lead: User, student: User, borrower: User) -> None:
    """The 100-Arduino example: a pool split across training, two competitions,
    R&D and borrowed, with a couple of units held by a named student so the
    "who has it" drill-down has real data. Idempotent by item name."""
    if db.scalar(select(InventoryItem).where(InventoryItem.name == "Arduino Uno R3")):
        return

    # competitions the allocations link to — RoboCup has the full nesting:
    # PM → category (Senior) → team (Robotics A, led by the team lead) → members
    robocup = Competition(name="RoboCup 2026", status=CompetitionStatus.ACTIVE,
                          description="Annual robotics championship.")
    vex = Competition(name="VEX Worlds 2026", status=CompetitionStatus.ACTIVE)
    db.add_all([robocup, vex])
    db.flush()
    # who manages RoboCup 2026 / leads Robotics A is now a matter of
    # role-template occupancy (an org-chart concern, see seed_positions /
    # the admin-configured role templates), not a dedicated field here.
    senior = CompetitionCategory(competition_id=robocup.id, name="Senior")
    db.add(senior)
    db.flush()
    team_a = CompetitionTeam(category_id=senior.id, name="Robotics A")
    db.add(team_a)
    db.flush()
    db.add(CompetitionTeamMember(team_id=team_a.id, user_id=student.id))
    comp_member = db.scalar(select(User).where(User.email == "comp@org.local"))
    if comp_member is not None:
        db.add(CompetitionTeamMember(team_id=team_a.id, user_id=comp_member.id))

    arduino = InventoryItem(
        name="Arduino Uno R3",
        category="Microcontrollers",
        asset_tag="ARD-UNO",
        quantity=100,
        unit="board",
        location="Lab A — Shelf 3",
        condition=Condition.GOOD,
        notes="Shared microcontroller pool.",
        team_lead_id=team_lead.id,  # dedicated to the team lead's team
    )
    db.add(arduino)
    db.flush()

    P = AllocationPurpose
    allocations = [
        # 50 in training (general pool, no single holder)
        dict(quantity=50, purpose=P.TRAINING, label="Training program"),
        # 20 in competition RoboCup — 1 of them held by the student
        dict(quantity=19, purpose=P.COMPETITION, competition_id=robocup.id),
        dict(quantity=1, purpose=P.COMPETITION, competition_id=robocup.id, holder_id=student.id),
        # 10 in a second competition
        dict(quantity=10, purpose=P.COMPETITION, competition_id=vex.id),
        # 10 in R&D — 2 of them held by the student
        dict(quantity=8, purpose=P.RESEARCH, label="Line-follower R&D"),
        dict(quantity=2, purpose=P.RESEARCH, label="Line-follower R&D", holder_id=student.id),
        # 5 borrowed out
        dict(quantity=5, purpose=P.BORROWED, label="Lent to partner school", holder_id=borrower.id),
    ]  # 95 in use, 5 free
    for a in allocations:
        db.add(InventoryAllocation(item_id=arduino.id, **a))

    # whereabouts: stock the Arduinos into Lab A, then issue a few via a
    # checkout request (so the request <-> movement link has real data)
    lab = Location(name="Lab A — Shelf 3", kind="shelf")
    store = Location(name="Main Store — Cabinet 1", kind="room")
    db.add_all([lab, store])
    db.flush()
    db.add(StockMovement(item_id=arduino.id, quantity=100, to_location_id=lab.id,
                         actor_id=team_lead.id, reason="Initial stock-in"))
    db.flush()

    issued_req = InventoryRequest(
        item_id=arduino.id, requester_id=student.id, quantity=3,
        reason="R&D prototyping", status=InventoryRequestStatus.ISSUED,
        approver_id=team_lead.id, issued_at=datetime.now(timezone.utc),
    )
    db.add(issued_req)
    db.flush()
    record_movement(
        db, arduino, 3, from_location_id=lab.id, from_holder_id=None,
        to_location_id=None, to_holder_id=student.id, actor_id=team_lead.id,
        reason=f"Issued via request #{issued_req.id}", request_id=issued_req.id,
    )

    comp_member = db.scalar(select(User).where(User.email == "comp@org.local"))
    if comp_member is not None:
        db.add(InventoryRequest(
            item_id=arduino.id, requester_id=comp_member.id, quantity=2,
            reason="Competition spares", needed_by=date.today() + timedelta(days=3),
        ))  # left submitted, so there's something waiting for review

    # a couple of general-storage items (staff-only, no team designation)
    db.add(InventoryItem(
        name="Raspberry Pi 4 (4GB)", category="Single-board computers", asset_tag="RPI4",
        quantity=15, low_stock_threshold=15, unit="board", location="Lab A — Cabinet 1",
        condition=Condition.GOOD, notes="General storage. Flagged low on purpose for the demo.",
    ))
    db.add(InventoryItem(
        name="PLA Filament 1kg", category="Consumables", quantity=40, unit="roll",
        location="Media room", condition=Condition.NEW, notes="Assorted colours.",
    ))
    db.flush()


def seed_positions(db: Session) -> None:
    """Mirror the demo org as a Position tree with occupants, leaving the
    Software Lead seat vacant to show a real empty position. Idempotent."""
    if db.scalar(select(Position)) is not None:
        return

    def user_id(email: str) -> int | None:
        u = db.scalar(select(User).where(User.email == email))
        return u.id if u else None

    def pos(title: str, parent: Position | None, email: str | None = None, tech: bool = False) -> Position:
        p = Position(
            title=title,
            parent_id=parent.id if parent else None,
            is_technical=tech,
        )
        db.add(p)
        db.flush()
        occ = user_id(email) if email else None
        if occ is not None:
            db.add(PositionOccupant(position_id=p.id, user_id=occ))
            db.flush()
        return p

    ceo = pos("CEO", None, "ceo@org.local")
    cto = pos("CTO", ceo, "cto@org.local", tech=True)
    sw_lead = pos("Software Lead", cto, None, tech=True)  # vacant seat
    pos("Software Member", sw_lead, "sw.emp@org.local", tech=True)
    mech_lead = pos("Mechanical Lead", cto, "mech.lead@org.local", tech=True)
    pos("Mechanical Member", mech_lead, "mech.emp@org.local", tech=True)
    elec_lead = pos("Electrical Lead", cto, "elec.lead@org.local", tech=True)
    pos("Electrical Member", elec_lead, "elec.emp@org.local", tech=True)
    cfo = pos("CFO", ceo, "cfo@org.local")
    pos("Finance Member", cfo, "fin.emp@org.local")
    media = pos("Media Lead", ceo, "media@org.local")
    pos("Media Member", media, "media.emp@org.local")
    pm = pos("Project Manager", ceo, "pm@org.local")
    tl = pos("Team Lead", pm, "teamlead@org.local")
    pos("Student", tl, "student@org.local")
    pos("Competition Member", tl, "comp@org.local")

    resync_managers(db)
    db.flush()


def seed_admin(db: Session, roles: dict[str, Role]) -> User:
    """The one always-present account: a technical admin so the portal is
    usable on a fresh database. Email/password come from SEED_ADMIN_EMAIL /
    SEED_ADMIN_PASSWORD (defaults below) — change them for a real deployment."""
    email = os.getenv("SEED_ADMIN_EMAIL", "admin@org.local")
    password = os.getenv("SEED_ADMIN_PASSWORD", DEV_PASSWORD)
    admin = db.scalar(select(User).where(User.email == email))
    if admin is None:
        admin = User(
            email=email, full_name="Technical Admin", hashed_password=hash_password(password)
        )
        db.add(admin)
        db.flush()
        db.add(UserRole(user_id=admin.id, role_id=roles[RoleSlug.ADMIN].id))
    return admin


def seed_demo(db: Session, roles: dict[str, Role]) -> None:
    """Optional sample org, tasks, requests and inventory — only for exploring
    the app. Run with `--demo`. Idempotent."""
    ensure_user(db, roles, "admin@org.local", "Technical Admin", [RoleSlug.ADMIN])
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

    # org chart: positions mirroring the people, with one vacant seat
    seed_positions(db)

    # inventory: the 100-Arduino allocation example (dedicated to the team
    # lead's team; the student holds a few units so drill-down has data)
    seed_inventory(db, team_lead=team_lead, student=student, borrower=sw_emp)

    # a pending request: PM -> CTO (across branches)
    if db.scalar(select(WorkRequest).where(WorkRequest.title == "Need a build server")) is None:
        db.add(WorkRequest(
            requester_id=pm.id, recipient_id=cto.id,
            title="Need a build server",
            description="The competition team needs CI for their firmware.",
            priority=TaskPriority.HIGH, status=RequestStatus.PENDING,
        ))


def run(demo: bool = False) -> None:
    """Default: roles + a single admin account (real-ready, no sample data).
    With demo=True, also load the sample org, tasks, requests and inventory."""
    Base.metadata.create_all(engine)
    db = SessionLocal()
    try:
        roles = seed_roles(db)
        admin = seed_admin(db, roles)
        if demo:
            seed_demo(db, roles)
        db.commit()

        if demo:
            print("Seeded roles + demo org. All demo accounts use password:", DEV_PASSWORD)
            print("Try: admin@org.local, ceo@org.local, cto@org.local (multi-role), "
                  "mech.lead@org.local, sw.emp@org.local, pm@org.local, "
                  "teamlead@org.local, student@org.local")
        else:
            pw = "SEED_ADMIN_PASSWORD" if os.getenv("SEED_ADMIN_PASSWORD") else f"'{DEV_PASSWORD}'"
            print("Seeded roles + admin bootstrap account (no sample data).")
            print(f"Admin login: {admin.email}  (password: {pw})")
            print("Add real users, teams and inventory through the app. "
                  "Re-run with `--demo` to load the sample org for testing.")
    finally:
        db.close()


if __name__ == "__main__":
    run(demo="--demo" in sys.argv)
