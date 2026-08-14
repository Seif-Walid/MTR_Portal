"""Give every account a member profile row.

The roster record (MemberProfile) used to be born only from the student-sheet
import, so accounts created any other way — Google sign-ups, the bootstrap
admin, old-DB carryovers — had no profile and couldn't be given member
details. New signups now get an empty profile automatically; this backfills
the ones that predate that.

Idempotent: only accounts missing a profile get one (empty, all fields null),
so re-running is a no-op.

Usage (from backend/, with the venv):
    DATABASE_URL=sqlite:///./portal_dev.db \\
        .venv/bin/python -m scripts.backfill_profiles
    # add --commit to write; without it, reports the count and rolls back.
"""

import argparse
import sys

from sqlalchemy import select

from app.core.database import SessionLocal
from app.domains.access.models import AccessLevel  # noqa: F401 — register mapper for User.access_level
from app.domains.users.models import MemberProfile, User


def run(commit: bool) -> int:
    db = SessionLocal()
    missing = list(
        db.scalars(
            select(User)
            .outerjoin(MemberProfile, MemberProfile.user_id == User.id)
            .where(MemberProfile.id.is_(None))
        )
    )
    for user in missing:
        db.add(MemberProfile(user_id=user.id))

    print(f"accounts missing a profile: {len(missing)}")
    if commit:
        db.commit()
        print("COMMITTED.")
    else:
        db.rollback()
        print("DRY RUN — nothing written.")
    db.close()
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true", help="write to the DB (default: dry run)")
    args = ap.parse_args()
    sys.exit(run(args.commit))
