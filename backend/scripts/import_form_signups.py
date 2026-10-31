"""Add the new members from a Google Form sign-up sheet to the roster.

Reads a form's responses (downloaded as .xlsx — "Form Responses 1" tab) with
the columns Timestamp, Email Address, Name and a phone column (any header
containing "phone"), and adds everyone the roster doesn't know yet:

  * a response is an existing member when its email or
    phone number already belongs to someone on the roster — existing members
    are left alone, except that blank roster fields get the form's value;
  * a new member gets the next MTR ID and a portal account pre-linked to
    Google at the Member level (same as the member database import), so they
    sign straight in with that Gmail;
  * a new member whose *name* matches someone already on the roster (but not
    their email or phone) is still added, flagged "review" with a note naming
    the look-alike, so a person can merge them if they're the same student;
  * the same email answering twice counts once (the latest answer wins).

Idempotent: re-running finds everyone by email and adds nothing.

Usage (from backend/):
    python -m scripts.import_form_signups RESPONSES.xlsx "General training season 4"           # dry run
    python -m scripts.import_form_signups RESPONSES.xlsx "General training season 4" --commit
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import openpyxl
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.security import UNUSABLE_PASSWORD
from app.domains.access.models import AccessLevel
from app.domains.members.service import digits, name_key, roster
from app.domains.users.models import User
from app.domains.users.roster import next_mtr_id

MEMBER_LEVEL = "Member"
# Google Forms stamps responses in the form owner's local time. The slim
# Docker image may lack the tz database; Cairo's summer offset is close enough.
try:
    FORM_TZ = ZoneInfo("Africa/Cairo")
except ZoneInfoNotFoundError:
    FORM_TZ = timezone(timedelta(hours=3))


def text(v) -> str | None:
    if v is None:
        return None
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    t = re.sub(r"\s+", " ", str(v)).strip()
    return t or None


def egyptian_phone(v) -> str | None:
    """'0127 537 3555', '+20 1555866198', 1207080642 -> '01xxxxxxxxx'."""
    d = re.sub(r"\D", "", text(v) or "")
    if d.startswith("20") and len(d) == 12:
        d = d[2:]
    if len(d) == 10 and d.startswith("1"):
        d = "0" + d
    return d or None


def read_responses(path: str) -> list[dict]:
    ws = openpyxl.load_workbook(path, read_only=True, data_only=True).worksheets[0]
    rows = ws.iter_rows(values_only=True)
    headers = [text(h) or "" for h in next(rows)]

    def col(pred) -> int:
        return next(i for i, h in enumerate(headers) if pred(h.lower()))

    i_time = col(lambda h: h == "timestamp")
    i_email = col(lambda h: "email" in h)
    i_name = col(lambda h: h == "name")
    i_phone = col(lambda h: "phone" in h)
    latest: dict[str, dict] = {}
    for r in rows:
        r = list(r) + [None] * len(headers)
        email = (text(r[i_email]) or "").lower()
        if not email:
            continue
        stamp = r[i_time]
        joined = stamp.replace(tzinfo=FORM_TZ).astimezone(timezone.utc) if isinstance(stamp, datetime) else None
        row = {"email": email, "name": text(r[i_name]), "phone": egyptian_phone(r[i_phone]), "joined_at": joined}
        prev = latest.get(email)
        if prev is None or (joined and prev["joined_at"] and joined > prev["joined_at"]):
            latest[email] = row
    return list(latest.values())


def run(db: Session, path: str, source: str) -> None:
    responses = read_responses(path)
    members = roster(db)
    users_by_email = {m.email.lower(): m for m in members if m.email}
    member_level = db.scalar(select(AccessLevel).where(AccessLevel.name == MEMBER_LEVEL))
    if member_level is None:
        print(f"  ! no '{MEMBER_LEVEL}' access level — new accounts get none")

    added = existing = 0
    now = datetime.now(timezone.utc)
    for r in sorted(responses, key=lambda r: r["joined_at"] or now):
        phone = digits(r["phone"])
        m = users_by_email.get(r["email"])
        how = "email"
        if m is None and phone:
            m, how = next((m for m in members if digits(m.phone) == phone), None), "phone"
        if m is not None:
            existing += 1
            form = {"full_name": r["name"], "email": r["email"], "phone": r["phone"]}
            filled = [k for k, v in form.items() if v and getattr(m, k) is None]
            for k in filled:
                setattr(m, k, form[k])
            extra = f"  (filled {', '.join(filled)})" if filled else ""
            print(f"  = {m.mtr_id or '-':<8} {m.full_name}  <- {r['email']} [by {how}]{extra}")
            continue

        look_alike = next((m for m in members if r["name"] and name_key(m.full_name) == name_key(r["name"])), None)
        p = User(
            mtr_id=next_mtr_id(db),
            full_name=r["name"] or r["email"].split("@")[0],
            email=r["email"],
            # pre-linked to the Gmail they signed up with: they sign straight in
            hashed_password=UNUSABLE_PASSWORD,
            google_linked_at=now,
            access_level_id=member_level.id if member_level else None,
            phone=r["phone"],
            joined_at=r["joined_at"],
            data_confidence="review" if look_alike else "single",
            source_records=1,
            review_note=(
                f"Signed up via '{source}'; same name as {look_alike.mtr_id or '#' + str(look_alike.id)} "
                f"({look_alike.full_name}) — merge if it's the same person"
                if look_alike else None
            ),
        )
        db.add(p)
        db.flush()
        users_by_email[r["email"]] = p
        members.append(p)
        added += 1
        flag = f"  ! same name as {look_alike.mtr_id} {look_alike.full_name}" if look_alike else ""
        print(f"  + {p.mtr_id:<8} {p.full_name}  <{p.email}> {p.phone or ''}{flag}")
    print(f"\n  responses (unique emails) {len(responses):>4}\n  already on the roster     {existing:>4}\n  new members added         {added:>4}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("responses_xlsx")
    ap.add_argument("source", help="the form's name, recorded on flagged rows")
    ap.add_argument("--commit", action="store_true", help="write the changes (default: dry run)")
    args = ap.parse_args()
    db = SessionLocal()
    try:
        print("COMMITTING" if args.commit else "DRY RUN — nothing written (pass --commit)")
        run(db, args.responses_xlsx, args.source)
        if args.commit:
            db.commit()
        else:
            db.rollback()
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
