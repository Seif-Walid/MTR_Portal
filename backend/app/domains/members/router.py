"""The member roster — the portal's copy of the member database. A member is
a person (User): adding one here creates their account, unclaimed until they
first sign in. Viewing is gated by members.view, adding/editing by members.edit."""

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.domains.access import service as access
from app.domains.audit.service import log as audit_log
from app.domains.auth.deps import DB, CurrentUser
from app.domains.events.models import EventParticipation
from app.domains.members import service
from app.domains.members.schemas import (
    DuplicateCheckIn,
    DuplicateHit,
    MemberDetail,
    MemberIn,
    MemberRow,
    ParticipationOut,
)
from app.domains.users.models import User
from app.domains.users.roster import new_member, next_mtr_id

router = APIRouter(prefix="/members", tags=["members"])


def _event_label(p: EventParticipation) -> str:
    return p.event.code or p.event.name


def _row(m: User, parts: list[EventParticipation]) -> dict:
    return {
        "id": m.id,
        "mtr_id": m.mtr_id,
        "name": m.full_name,
        "email": m.email,
        "phone": m.phone,
        "university": m.university,
        "college": m.college,
        "major": m.major,
        "graduating_year": m.graduating_year,
        "location": m.location,
        "joined_at": m.joined_at,
        "data_confidence": m.data_confidence,
        "claimed": m.claimed,
        "is_active": m.is_active,
        "events": [_event_label(p) for p in sorted(parts, key=lambda p: p.event.start_date or p.event.created_at.date(), reverse=True)],
    }


def _participation_out(p: EventParticipation) -> ParticipationOut:
    e = p.event
    return ParticipationOut(
        id=p.id, event_id=e.id, event_name=e.name, event_code=e.code,
        event_kind=e.kind.name if e.kind else None, event_start=e.start_date,
        role=p.role, team=p.team, mentor=p.mentor, rating=p.rating, registered_at=p.registered_at,
    )


def _detail(db: DB, m: User) -> MemberDetail:
    parts = list(db.scalars(select(EventParticipation).where(EventParticipation.member_id == m.id)))
    parts.sort(key=lambda p: p.event.start_date or p.event.created_at.date(), reverse=True)
    return MemberDetail(
        **_row(m, parts),
        full_name=m.full_name,
        national_id=m.national_id,
        birthday=m.birthday,
        guardian_phone=m.guardian_phone,
        guardian_kinship=m.guardian_kinship,
        uni_id=m.uni_id,
        source_records=m.source_records,
        review_note=m.review_note,
        participations=[_participation_out(p) for p in parts],
    )


def _redact(db: DB, user, out):
    """Blank the roster fields this viewer may not see (column-level privileges)."""
    from app.domains.bulk.registry import restricted_attrs

    hidden = restricted_attrs("users", access.privileges_for(db, user))
    if not hidden:
        return out
    if isinstance(out, list):
        return [_redact_one(o, hidden) for o in out]
    return _redact_one(out, hidden)


def _redact_one(o, hidden: set[str]):
    return o.model_copy(update={k: None for k in hidden if k in type(o).model_fields})


def _get(db: DB, member_id: int) -> User:
    m = db.get(User, member_id)
    if m is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Member not found")
    return m


@router.get("")
def list_members(db: DB, user: CurrentUser) -> list[MemberRow]:
    access.require_privilege(db, user, "members.view")
    parts = service.participations_by_member(db)
    return _redact(db, user, [MemberRow(**_row(m, parts.get(m.id, []))) for m in service.roster(db)])


@router.get("/stats")
def member_stats(db: DB, user: CurrentUser) -> dict:
    access.require_privilege(db, user, "members.view")
    return service.stats(db)


@router.get("/next-id")
def next_id(db: DB, user: CurrentUser) -> dict:
    access.require_privilege(db, user, "members.edit")
    return {"mtr_id": next_mtr_id(db)}


@router.post("/check-duplicate")
def check_duplicate(payload: DuplicateCheckIn, db: DB, user: CurrentUser) -> list[DuplicateHit]:
    """Does someone on the roster already share this name / phone / email?"""
    access.require_privilege(db, user, "members.edit")
    return [
        DuplicateHit(id=m.id, mtr_id=m.mtr_id, name=m.full_name, matched_on=why)
        for m, why in service.find_duplicates(db, payload.name, payload.phone, payload.email, payload.exclude_id)
    ]


@router.get("/{member_id}")
def get_member(member_id: int, db: DB, user: CurrentUser) -> MemberDetail:
    access.require_privilege(db, user, "members.view")
    return _redact(db, user, _detail(db, _get(db, member_id)))


def _apply(db: DB, m: User, data: dict) -> None:
    data = {k: (v.strip() if isinstance(v, str) else v) for k, v in data.items()}
    data = {k: (None if v == "" else v) for k, v in data.items()}
    if "full_name" in data and not data["full_name"]:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A member needs a name")
    if data.get("email"):
        data["email"] = data["email"].lower()
        clash = db.scalar(select(User).where(User.email == data["email"], User.id != (m.id or -1)))
        if clash is not None:
            raise HTTPException(status.HTTP_409_CONFLICT, f"{data['email']} is already {clash.full_name}'s")
    mtr_id = data.get("mtr_id")
    if mtr_id:
        clash = db.scalar(select(User).where(User.mtr_id == mtr_id, User.id != (m.id or -1)))
        if clash is not None:
            raise HTTPException(status.HTTP_409_CONFLICT, f"MTR ID {mtr_id} is already {clash.full_name}'s")
    for k, v in data.items():
        setattr(m, k, v)


@router.post("", status_code=status.HTTP_201_CREATED)
def create_member(payload: MemberIn, db: DB, user: CurrentUser) -> MemberDetail:
    """Add a member — which is creating their account. It starts unclaimed (no
    password); its owner claims it by signing in with Google or a reset link
    sent to the email."""
    access.require_privilege(db, user, "members.edit")
    data = payload.model_dump(exclude_unset=True)
    if not (data.get("full_name") or "").strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A member needs a name")
    m = new_member(db)
    if not data.get("mtr_id"):
        data["mtr_id"] = next_mtr_id(db)
    data.setdefault("data_confidence", "manual")
    data.setdefault("source_records", 1)
    _apply(db, m, data)
    db.add(m)
    db.flush()
    audit_log(db, user.id, "members", "created", "member", m.id, {"name": m.full_name, "mtr_id": m.mtr_id})
    db.commit()
    db.refresh(m)
    return _detail(db, m)


@router.patch("/{member_id}")
def update_member(member_id: int, payload: MemberIn, db: DB, user: CurrentUser) -> MemberDetail:
    access.require_privilege(db, user, "members.edit")
    m = _get(db, member_id)
    _apply(db, m, payload.model_dump(exclude_unset=True))
    audit_log(db, user.id, "members", "updated", "member", m.id, {"name": m.full_name})
    db.commit()
    db.refresh(m)
    return _detail(db, m)


@router.delete("/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_member(member_id: int, db: DB, user: CurrentUser) -> None:
    """Remove a member nobody ever signed into (e.g. a duplicate) who has no
    dues on the books. Anyone else is retired by deactivating them."""
    access.require_privilege(db, user, "members.edit")
    m = _get(db, member_id)
    from app.domains.bulk.service import member_delete_blocker

    reason = member_delete_blocker(db, m)
    if reason:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, reason)
    audit_log(db, user.id, "members", "deleted", "member", m.id, {"name": m.full_name, "mtr_id": m.mtr_id})
    db.delete(m)
    db.commit()
