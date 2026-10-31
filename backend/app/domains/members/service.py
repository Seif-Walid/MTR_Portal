"""Roster queries: duplicate detection (the old "Add Members" sheet's check),
and the aggregate statistics behind the dashboard."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domains.events.models import Event, EventParticipation
from app.domains.users.models import User


def digits(phone: str | None) -> str | None:
    """Last 10 digits of a phone number, so 01x… / +201x… / spacing all match."""
    d = re.sub(r"\D", "", phone or "")
    return d[-10:] if len(d) >= 10 else None


def name_key(name: str | None) -> str:
    return re.sub(r"[^a-z؀-ۿ]", "", (name or "").lower())


def roster(db: Session) -> list[User]:
    """Every member — which is every person: a member and an account are one row."""
    return list(db.scalars(select(User).order_by(User.id)))


def find_duplicates(
    db: Session, name: str | None, phone: str | None, email: str | None, exclude_id: int | None = None
) -> list[tuple[User, list[str]]]:
    want_name, want_phone = name_key(name), digits(phone)
    want_email = (email or "").strip().lower()
    hits = []
    for m in roster(db):
        if m.id == exclude_id:
            continue
        why = []
        if want_name and name_key(m.full_name) == want_name:
            why.append("name")
        if want_phone and digits(m.phone) == want_phone:
            why.append("phone")
        if want_email and want_email == (m.email or "").lower():
            why.append("email")
        if why:
            hits.append((m, why))
    return hits


def participations_by_member(db: Session) -> dict[int, list[EventParticipation]]:
    out: dict[int, list[EventParticipation]] = defaultdict(list)
    for p in db.scalars(select(EventParticipation)):
        out[p.member_id].append(p)
    return out


def _top(counter: Counter, n: int = 12) -> list[dict]:
    return [{"name": k, "count": v} for k, v in counter.most_common(n)]


def stats(db: Session) -> dict:
    """Roster statistics. Counted over numbered members (those with an MTR ID)
    — accounts that never made it onto the roster (bootstrap admins, test
    logins, people dropped from the member database) carry no MTR ID."""
    everyone = roster(db)
    members = [m for m in everyone if m.mtr_id]
    numbered = {m.id for m in members}
    parts = [p for p in db.scalars(select(EventParticipation)) if p.member_id in numbered]
    events = {e.id: e for e in db.scalars(select(Event))}

    joins = Counter(m.joined_at.strftime("%Y-%m") for m in members if m.joined_at)
    by_event: dict[int, int] = Counter(p.event_id for p in parts)
    per_member = Counter(p.member_id for p in parts)
    activity = Counter(per_member.get(m.id, 0) for m in members)

    def clean(v) -> str:
        return (str(v).strip() if v not in (None, "") else "Unknown") or "Unknown"

    event_rows = []
    for eid, count in by_event.items():
        e = events.get(eid)
        if e is None:
            continue
        event_rows.append({
            "id": e.id, "name": e.name, "code": e.code,
            "kind": e.kind.name if e.kind else None,
            "start_date": e.start_date.isoformat() if e.start_date else None,
            "status": e.status, "participants": count, "result": e.result,
        })
    event_rows.sort(key=lambda r: (r["start_date"] or "", r["name"]), reverse=True)

    year_now = datetime.now().year
    return {
        "totals": {
            "members": len(members),
            "unnumbered": len(everyone) - len(members),
            "claimed": sum(1 for m in members if m.claimed),
            "unclaimed": sum(1 for m in members if not m.claimed),
            "needs_review": sum(1 for m in members if m.data_confidence == "review"),
            "participations": len(parts),
            "active_members": sum(1 for m in members if per_member.get(m.id)),
            "graduating_soon": sum(
                1 for m in members if m.graduating_year and year_now <= m.graduating_year <= year_now + 1
            ),
        },
        "by_university": _top(Counter(clean(m.university) for m in members)),
        "by_major": _top(Counter(clean(m.major) for m in members)),
        "by_location": _top(Counter(clean(m.location) for m in members)),
        "by_graduating_year": sorted(
            ({"name": str(k), "count": v} for k, v in Counter(m.graduating_year for m in members if m.graduating_year).items()),
            key=lambda r: r["name"],
        ),
        "by_confidence": _top(Counter(clean(m.data_confidence) for m in members)),
        "joins_by_month": [{"month": k, "count": v} for k, v in sorted(joins.items())],
        "activity": [{"events": k, "members": v} for k, v in sorted(activity.items())],
        "events": event_rows,
    }
