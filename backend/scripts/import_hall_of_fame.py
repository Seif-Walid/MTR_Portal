"""One-time import of the website's Hall of Fame (roster.json) into the portal DB.

Each competition record becomes an ARCHIVED event of the "competition" kind; its
groups become categories -> teams (label = team, sublabel = category), and each
listed member becomes an EventTeamMember linked to the person's portal account,
carrying their verbatim competition role.

Member -> account resolution:
  * A small EXPLICIT map pins ambiguous single names to a specific account.
  * A small CREATE_NEW set is for roster people who have no portal account: a
    placeholder account is synthesized (is_active=False, unusable password,
    email firstname.lastname@mindtechrobotics.com), department taken from their
    roster role when it names a real org department.
  * Everyone else is fuzzy-matched to an existing user by normalized name. A
    match must be confident and unambiguous; if ANY member cannot be resolved,
    the script writes nothing and reports them, so no one is mis-credited.

Idempotent: an event whose name already exists is skipped; placeholder accounts
are matched by email and reused. Dry run by default — pass --commit to write.

Usage (from backend/, with the venv):
    DATABASE_URL=sqlite:///./portal_dev.db \\
        .venv/bin/python -m scripts.import_hall_of_fame ../MTR_Website/data/roster.json
    # add --commit to persist.
"""

import argparse
import re
import secrets
import sys
import unicodedata
from datetime import date

from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.security import hash_password

# Import every model module so SQLAlchemy's registry can resolve the string
# relationship targets (User -> AccessLevel, etc.) referenced across domains.
from app.domains.access import models as _access  # noqa: F401
from app.domains.audit import models as _audit  # noqa: F401
from app.domains.auth import models as _auth  # noqa: F401
from app.domains.inventory import models as _inventory  # noqa: F401
from app.domains.notifications import models as _notifications  # noqa: F401
from app.domains.positions import models as _positions  # noqa: F401
from app.domains.requests import models as _requests  # noqa: F401
from app.domains.sync import models as _sync  # noqa: F401
from app.domains.tasks import models as _tasks  # noqa: F401
from app.domains.timeblocks import models as _timeblocks  # noqa: F401
from app.domains.events.models import (
    Event,
    EventCategory,
    EventKind,
    EventStatus,
    EventTeam,
    EventTeamMember,
)
from app.domains.users.models import Department, User

# Ambiguous or differently-spelled roster names pinned to an exact existing
# account (matched by full_name, case-insensitive). Resolved against the LIVE
# prod users with the owner (2026-08-28): the two leaders are the seated CEO/CTO.
EXPLICIT: dict[str, str] = {
    "Essam": "Essam Ahmed",
    "Ganna": "Ganna",
    "Ahmed Hisham": "Ahmed hisham shaker",
    "Mahmoud Mohamed Mahmoud": "Mahmoud Mohamed Mahmoud",
    "Youssef Mohamed": "Youssef Mohamed",
    "Mostafa Mohamed Mostafa": "Mostafa mohamed mostafa Erakat",
    "Amr Khaled Mohamed": "Amr Khaled Mohamed",  # seated CTO (Pilot · CTO)
    "Osama El-Azab": "Osama Medhat",  # seated CEO (roster surname differs)
    # "Yahya Hamdy Hassan" had a duplicate account; the owner deleted the
    # @mtr.eg one and kept the gmail account. Pin by that surviving email (both
    # roster spellings are the same competitor).
    "Yahya Hamdy": "yahiahamdy2007@gmail.com",
    "Yahya Hamdy Hassan": "yahiahamdy2007@gmail.com",
}

# A value containing "@" pins by email (portable across dev/prod, and the only
# way to disambiguate duplicate full names); otherwise it pins by full_name.

# Roster people with no portal account — synthesize a placeholder credit account.
# "Amr Khaled El Shiekh" is a DIFFERENT person from the CTO "Amr Khaled Mohamed"
# (never co-occur; El Shiekh only in MRC 2024).
CREATE_NEW: set[str] = {
    "Dina Ibrahim",
    "Amr Khaled El Shiekh",
    "Mohanned Mohammed",
    "Jana Mohamad Saeed",
}

# Real email/role for create-new people the members sheet knows about, so the
# placeholder account is created with their true login rather than a synthetic one.
CREATE_ACCOUNT_EMAIL: dict[str, str] = {
    "Jana Mohamad Saeed": "janamohamadsaeed@gmail.com",
}

_VALID_DEPARTMENTS = {d.value for d in Department}


def normalize(s: str) -> set[str]:
    """Fold to a comparable token set: strip accents/punctuation, lowercase, and
    collapse the common Arabic-name spelling variants that differ between the
    roster sheet and the portal roster."""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = s.lower().replace("'", "")
    s = re.sub(r"[^a-z ]", " ", s)
    s = (
        s.replace("el ", "el")
        .replace("abdel", "abd")
        .replace("mohammed", "mohamed")
        .replace("mohamad", "mohamed")
        .replace("muhammed", "mohamed")
        .replace("abdelrahman", "abdrahman")
        .replace("abdelrhman", "abdrahman")
        .replace("abdulrahman", "abdrahman")
    )
    return {t for t in s.split() if len(t) > 1}


def slug_email(name: str) -> str:
    base = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    base = re.sub(r"[^a-z ]", "", base).strip()
    base = ".".join(base.split())
    return f"{base}@mindtechrobotics.com"


def department_for(role: str | None) -> str | None:
    if role and role.lower() in _VALID_DEPARTMENTS:
        return role.lower()
    return None


def fuzzy_match(name: str, candidates: list[tuple[object, set[str]]]) -> object | None:
    """Pick the single best account for a roster name from (key, token_set)
    candidates, or None if no confident/unambiguous match. Pure — no DB — so the
    same logic validates offline against a prod user dump and runs live."""
    tn = normalize(name)
    if not tn:
        return None
    scored = []
    for key, tu in candidates:
        if not tu:
            continue
        inter = len(tn & tu)
        if inter < 2:
            continue
        if tn <= tu or tu <= tn or inter / max(len(tn), 1) >= 0.6:
            scored.append((inter, key))
    if not scored:
        return None
    scored.sort(key=lambda x: x[0], reverse=True)
    # Require the best to strictly beat the runner-up (unambiguous).
    if len(scored) > 1 and scored[0][0] == scored[1][0]:
        return None
    return scored[0][1]


class Resolver:
    def __init__(self, db):
        self.db = db
        self.users = [(u, normalize(u.full_name)) for u in db.scalars(select(User)).all()]
        self._by_name = {u.full_name.lower(): u for u, _ in self.users}
        self._by_email = {u.email.lower(): u for u, _ in self.users if u.email}
        self._created: dict[str, User] = {}
        self.unresolved: list[str] = []

    def _fuzzy(self, name: str) -> User | None:
        return fuzzy_match(name, self.users)

    def _pinned(self, target: str) -> User | None:
        # "@" in the target -> pin by email (disambiguates duplicate names);
        # otherwise pin by full_name.
        if "@" in target:
            return self._by_email.get(target.lower())
        return self._by_name.get(target.lower())

    def resolve(self, name: str, role: str | None) -> User | None:
        name = name.strip()
        if name in EXPLICIT:
            u = self._pinned(EXPLICIT[name])
            if u is None:
                self.unresolved.append(f"{name!r} (explicit -> {EXPLICIT[name]!r} not found)")
            return u
        if name in CREATE_NEW:
            return self._get_or_create(name, role)
        u = self._fuzzy(name)
        if u is None:
            self.unresolved.append(f"{name!r} (no confident match)")
        return u

    def _get_or_create(self, name: str, role: str | None) -> User:
        # Prefer the person's real email from the members sheet; fall back to a
        # synthetic address only when we don't know it.
        email = CREATE_ACCOUNT_EMAIL.get(name, slug_email(name))
        if email in self._created:
            return self._created[email]
        u = self.db.scalar(select(User).where(User.email == email))
        if u is None:
            u = User(
                email=email,
                full_name=name,
                hashed_password=hash_password(secrets.token_urlsafe(16)),
                department=department_for(role),
                is_active=False,
            )
            self.db.add(u)
            self.db.flush()
            self.created_this_run.append(u)
        self._created[email] = u
        return u


def run(roster_path: str, commit: bool) -> int:
    import json

    with open(roster_path, encoding="utf-8") as f:
        records = json.load(f)

    db = SessionLocal()
    resolver = Resolver(db)
    resolver.created_this_run = []

    kind = db.scalar(select(EventKind).where(EventKind.slug == "competition"))
    if kind is None:
        print("ERROR: no 'competition' event kind exists — cannot import.", file=sys.stderr)
        return 2

    made_events = 0
    skipped_events = 0
    made_members = 0

    for rec in records:
        name = rec["event"].strip()
        if db.scalar(select(Event).where(Event.name == name)):
            skipped_events += 1
            print(f"  skip (exists): {name}")
            continue
        year = rec.get("year")
        event = Event(
            name=name,
            kind_id=kind.id,
            start_date=date(year, 1, 1) if year else None,
            status=EventStatus.ARCHIVED,
            awards=rec.get("awards") or None,
        )
        db.add(event)
        db.flush()
        made_events += 1

        categories: dict[str, EventCategory] = {}
        for grp in rec.get("groups", []):
            label = grp["label"]
            sublabel = grp.get("sublabel")
            cat_name = sublabel or label  # no sublabel -> category named like the team
            cat = categories.get(cat_name)
            if cat is None:
                cat = EventCategory(event_id=event.id, name=cat_name)
                db.add(cat)
                db.flush()
                categories[cat_name] = cat
            team = EventTeam(category_id=cat.id, name=label, award=grp.get("award"))
            db.add(team)
            db.flush()
            seen: set[int] = set()
            for m in grp.get("members", []):
                user = resolver.resolve(m["name"], m.get("role"))
                if user is None:
                    continue  # unresolved recorded; will abort below
                if user.id in seen:
                    continue
                seen.add(user.id)
                db.add(EventTeamMember(team_id=team.id, user_id=user.id, role=m.get("role")))
                made_members += 1

    if resolver.unresolved:
        print("\nUNRESOLVED members — nothing written. Fix EXPLICIT/CREATE_NEW or the roster:")
        for u in sorted(set(resolver.unresolved)):
            print("  -", u)
        db.rollback()
        return 1

    print("\nSummary:")
    print(f"  events created:  {made_events}")
    print(f"  events skipped:  {skipped_events} (already present)")
    print(f"  memberships:     {made_members}")
    print(f"  accounts created:{len(resolver.created_this_run)}")
    for u in resolver.created_this_run:
        print(f"     + {u.full_name} <{u.email}> dept={u.department or '-'} (inactive)")

    if commit:
        db.commit()
        print("\nCOMMITTED.")
    else:
        db.rollback()
        print("\nDRY RUN — nothing written. Re-run with --commit to persist.")
    db.close()
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("roster", help="path to roster.json")
    ap.add_argument("--commit", action="store_true", help="write to the DB (default: dry run)")
    args = ap.parse_args()
    sys.exit(run(args.roster, args.commit))


if __name__ == "__main__":
    main()
