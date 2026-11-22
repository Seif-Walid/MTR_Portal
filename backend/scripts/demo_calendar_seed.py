"""Fill a LOCAL database with a busy, believable schedule so the calendar can be
judged under load: events of every kind, overlapping team time blocks (event
teams and org units), tasks, work requests and inventory checkouts.

Every row it creates is recorded in a sidecar JSON next to the database, so
the demo can be removed exactly:

    DATABASE_URL=sqlite:///./portal_ai.db .venv/bin/python scripts/demo_calendar_seed.py
    DATABASE_URL=sqlite:///./portal_ai.db .venv/bin/python scripts/demo_calendar_seed.py --undo

Refuses to run against anything but SQLite. Never point it at portal_dev.db
(real roster/inventory) or production.
"""

import json
import random
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import app.seed  # noqa: F401  (registers every model)
from app.core.config import settings
from app.core.database import SessionLocal
from app.domains.events.models import Event, EventCategory, EventTeam, EventTeamMember
from app.domains.inventory.models import InventoryItem, InventoryRequest
from app.domains.positions.models import Position
from app.domains.requests.models import WorkRequest
from app.domains.tasks.models import Task
from app.domains.timeblocks.models import TimeBlock
from app.domains.users.models import User

URL = settings.database_url
if not URL.startswith("sqlite"):
    sys.exit("refusing: demo seed only runs against a local SQLite database")
if "portal_dev.db" in URL:
    sys.exit("refusing: portal_dev.db holds the real roster and inventory")
LEDGER = Path(URL.split("///", 1)[1]).with_suffix(".demo-calendar.json")

# delete children before parents
ORDER = [
    ("time_blocks", TimeBlock), ("tasks", Task), ("work_requests", WorkRequest),
    ("inventory_requests", InventoryRequest), ("event_team_members", EventTeamMember),
    ("event_teams", EventTeam), ("event_categories", EventCategory), ("events", Event),
]
MON, TUE, WED, THU, FRI, SAT, SUN = (1 << i for i in range(7))


def undo() -> None:
    if not LEDGER.exists():
        sys.exit(f"nothing to undo: {LEDGER.name} not found")
    ids = json.loads(LEDGER.read_text())
    db = SessionLocal()
    for key, model in ORDER:
        for i in ids.get(key, []):
            row = db.get(model, i)
            if row is not None:
                db.delete(row)
        db.flush()
    db.commit()
    LEDGER.unlink()
    print("demo calendar data removed")


def seed() -> None:
    if LEDGER.exists():
        sys.exit(f"already seeded ({LEDGER.name} exists) — run with --undo first")
    rnd = random.Random(1117)
    db = SessionLocal()
    made: dict[str, list[int]] = {k: [] for k, _ in ORDER}
    today = date.today()
    d = lambda n: today + timedelta(days=n)  # noqa: E731
    now = datetime.now(timezone.utc)

    def add(key: str, row):
        db.add(row)
        db.flush()
        made[key].append(row.id)
        return row

    admin = db.get(User, 1)
    people = list(db.query(User).filter(User.id > 2).order_by(User.id).limit(60))
    pick = lambda: rnd.choice(people)  # noqa: E731

    # ---- events of every kind ------------------------------------------------
    kinds = {"competition": 1, "training": 2, "rnd": 3}
    new_events = [
        ("Arduino Bootcamp", "training", d(4), d(6)),
        ("Battery Pack R&D", "rnd", d(-1), d(2)),
        ("Sumo Qualifiers", "competition", d(11), d(12)),
        ("Thruster R&D Sprint", "rnd", d(9), d(17)),
        ("ROS 2 Workshop", "training", d(19), d(20)),
        ("Winter Hackathon", "competition", d(25), d(27)),
        ("PCB Design Course", "training", d(-8), d(33)),
        ("Line Follower Cup", "competition", d(-12), d(-11)),
        ("Vision Lab Week", "rnd", d(-6), d(-2)),
    ]
    ev = {}
    for name, kind, s, e in new_events:
        ev[name] = add("events", Event(name=name, kind_id=kinds[kind], start_date=s, end_date=e, description="Demo"))

    def team(event: Event, cat: str, names: list[str]) -> list[EventTeam]:
        c = add("event_categories", EventCategory(event_id=event.id, name=cat))
        out = []
        for n in names:
            t = add("event_teams", EventTeam(category_id=c.id, name=n))
            for u in rnd.sample(people, 4):
                add("event_team_members", EventTeamMember(team_id=t.id, user_id=u.id))
            out.append(t)
        return out

    boot_a, boot_b = team(ev["Arduino Bootcamp"], "Groups", ["Group A", "Group B"])
    hack = team(ev["Winter Hackathon"], "Squads", ["Squad Volt", "Squad Torque", "Squad Pixel"])
    thr_mech, thr_elec = team(ev["Thruster R&D Sprint"], "Workstreams", ["Mechanical", "Electrical"])
    pcb = team(ev["PCB Design Course"], "Cohorts", ["Cohort 1", "Cohort 2"])

    # existing teams on the real events (MATE ROV team1, Robotida sumo/line/football)
    existing = {t.name: t for t in db.query(EventTeam).filter(EventTeam.deleted_at.is_(None))}

    # ---- time blocks: lots of overlap on purpose ------------------------------
    def block(team_obj=None, pos=None, title="", s=d(-20), e=d(45), mask=0, t0=None, t1=None):
        add("time_blocks", TimeBlock(
            team_type="event" if team_obj else "org",
            event_team_id=team_obj.id if team_obj else None,
            position_id=pos.id if pos else None,
            title=title, start_date=s, end_date=e, weekday_mask=mask,
            start_time=t0, end_time=t1, created_by=admin.id,
        ))

    H = lambda h, m=0: time(h, m)  # noqa: E731
    if "team1" in existing:
        block(existing["team1"], title="ROV pool session", mask=MON | WED, t0=H(16), t1=H(19))
        block(existing["team1"], title="ROV build night", mask=SAT, t0=H(12), t1=H(17))
    if "Sumo1" in existing:
        block(existing["Sumo1"], title="Sumo1 practice", mask=TUE | THU, t0=H(15), t1=H(18))
    if "Sumo2" in existing:
        block(existing["Sumo2"], title="Sumo2 practice", mask=TUE | THU, t0=H(16, 30), t1=H(19, 30))
    if "Line1" in existing:
        block(existing["Line1"], title="Line track tuning", mask=SUN, t0=H(10), t1=H(14))
    if "Football1" in existing:
        block(existing["Football1"], title="Football scrimmage", mask=MON | SAT, t0=H(17), t1=H(20))
    block(boot_a, s=d(4), e=d(6), t0=H(9), t1=H(13))
    block(boot_b, s=d(4), e=d(6), t0=H(14), t1=H(18))
    for i, t in enumerate(hack):
        block(t, s=d(25), e=d(27))  # all-day spans, three in parallel
    block(thr_mech, title="Thruster bench tests", s=d(9), e=d(17), mask=MON | WED | FRI, t0=H(10), t1=H(13))
    block(thr_elec, title="ESC firmware", s=d(9), e=d(17), mask=TUE | THU, t0=H(13), t1=H(16))
    block(pcb[0], title="PCB lecture", s=d(-8), e=d(33), mask=SUN, t0=H(18), t1=H(20))
    block(pcb[1], title="PCB lab", s=d(-8), e=d(33), mask=WED, t0=H(18), t1=H(20, 30))

    pos = {p.title.strip(): p for p in db.query(Position).filter(Position.entity_type.is_(None))}
    if "Electrical Lead" in pos:
        block(pos=pos["Electrical Lead"], title="Electrical sync", mask=WED, t0=H(19), t1=H(20))
    if "Software Lead" in pos:
        block(pos=pos["Software Lead"], title="Code review hour", mask=THU, t0=H(19), t1=H(21))
    if "Mechanical Lead " in pos or "Mechanical Lead" in pos:
        block(pos=pos.get("Mechanical Lead") or pos["Mechanical Lead "], title="Workshop lockdown", s=d(13), e=d(15))
    if "Media Manager" in pos:
        block(pos=pos["Media Manager"], title="Hackathon coverage", s=d(25), e=d(27))
    if "CEO" in pos:
        block(pos=pos["CEO"], title="Board meeting", mask=SUN, t0=H(20), t1=H(21, 30))

    # ---- tasks ---------------------------------------------------------------
    task_titles = [
        "Wire ESC harness", "CAD frame v3", "Order O-rings", "Tether strain test", "Pool booking email",
        "Camera mount print", "Sponsor deck draft", "Ballast calibration", "Write PID notes", "Solder sensor board",
        "Update BOM sheet", "Gripper servo swap", "Lab safety briefing", "Edit build vlog", "Thruster duct print",
        "Flash Pi image", "Leak test enclosure", "Buoyancy foam cut", "Line sensor array", "Sumo blade grind",
        "Football bot gearbox", "Media post: bootcamp", "Budget for Q1", "Clean workshop", "Inventory recount",
        "Motor driver test", "Write judging rubric", "Hackathon prompts", "Rules doc review", "Battery cycle log",
        "ROS 2 launch files", "Vision dataset labels", "Practice field setup", "Spare props order", "IMU calibration",
        "Wiring diagram v2", "Weekly report", "Shipping crate quote", "Travel forms", "Tool checkout audit",
    ]
    statuses = ["todo", "todo", "todo", "in_progress", "in_progress", "submitted", "approved"]
    for i, title in enumerate(task_titles):
        due = d(rnd.randint(-14, 40))
        st = rnd.choice(statuses)
        add("tasks", Task(
            title=title, assigner_id=admin.id, assignee_id=pick().id, due_date=due,
            priority=rnd.choice(["low", "medium", "medium", "high", "urgent"]), status=st,
        ))
    # a cluster on one day to stress "+N more"
    for title in ["Pre-ship checklist", "Pack spares", "Label crates", "Final wiring check", "Print team badges", "Charge all packs"]:
        add("tasks", Task(title=title, assigner_id=admin.id, assignee_id=pick().id, due_date=d(10), status="todo"))

    # ---- work requests -------------------------------------------------------
    req_titles = [
        "Need help on PID tuning", "Lab key handover", "Review my CAD", "Borrow oscilloscope time",
        "Photo shoot for sponsor", "Second pair of hands: tether", "Check my PCB footprint",
        "Help debug ROS node", "Proofread rules summary", "Cover my pool slot",
        "Design hackathon poster", "Approve travel budget", "Mentor Group B", "Repair sumo wheel",
    ]
    for t in req_titles:
        a, b = rnd.sample(people, 2)
        if rnd.random() < .4:
            a = admin  # some involve the admin so "Just me" isn't empty
        add("work_requests", WorkRequest(
            requester_id=a.id, recipient_id=b.id, title=t, due_date=d(rnd.randint(-5, 30)),
            status=rnd.choice(["pending", "pending", "accepted", "declined"]),
        ))

    # ---- inventory checkouts -------------------------------------------------
    items = list(db.query(InventoryItem).order_by(InventoryItem.id).limit(60))
    for _ in range(18):
        it = rnd.choice(items)
        mode = rnd.choice(["submitted", "approved", "issued", "issued"])
        needed = d(rnd.randint(0, 25))
        ret = d(rnd.randint(-6, 30))
        add("inventory_requests", InventoryRequest(
            item_id=it.id, requester_id=(admin if rnd.random() < .3 else pick()).id,
            quantity=rnd.randint(1, 4), reason="Demo", needed_by=needed,
            return_by=ret, status=mode,
            issued_at=now - timedelta(days=rnd.randint(1, 20)) if mode == "issued" else None,
        ))

    db.commit()
    LEDGER.write_text(json.dumps(made, indent=1))
    print({k: len(v) for k, v in made.items()})
    print(f"ledger: {LEDGER}")


if __name__ == "__main__":
    undo() if "--undo" in sys.argv else seed()
