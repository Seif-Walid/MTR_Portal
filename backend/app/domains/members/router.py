"""The member roster — the portal's copy of the member database. Members are
roster records (MemberProfile) whether or not they have a portal account;
viewing is gated by members.view, adding/editing by members.edit."""

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
from app.domains.users.models import MemberProfile, User
from app.domains.users.roster import next_mtr_id

router = APIRouter(prefix="/members", tags=["members"])


def _event_label(p: EventParticipation) -> str:
    return p.event.code or p.event.name


def _row(m: MemberProfile, parts: list[EventParticipation]) -> dict:
    return {
        "id": m.id,
        "mtr_id": m.mtr_id,
        "name": m.display_name,
        "email": m.user.email if m.user else m.email,
        "phone": m.phone,
        "university": m.university,
        "college": m.college,
        "major": m.major,
        "graduating_year": m.graduating_year,
        "location": m.location,
        "joined_at": m.joined_at,
        "data_confidence": m.data_confidence,
        "has_account": m.user_id is not None,
        "account_active": m.user.is_active if m.user else None,
        "events": [_event_label(p) for p in sorted(parts, key=lambda p: p.event.start_date or p.event.created_at.date(), reverse=True)],
    }


def _participation_out(p: EventParticipation) -> ParticipationOut:
    e = p.event
    return ParticipationOut(
        id=p.id, event_id=e.id, event_name=e.name, event_code=e.code,
        event_kind=e.kind.name if e.kind else None, event_start=e.start_date,
        role=p.role, team=p.team, mentor=p.mentor, rating=p.rating, registered_at=p.registered_at,
    )


def _detail(db: DB, m: MemberProfile) -> MemberDetail:
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
        account_email=m.user.email if m.user else None,
        participations=[_participation_out(p) for p in parts],
    )


def _redact(db: DB, user, out):
    """Blank the roster fields this viewer may not see (column-level privileges)."""
    from app.domains.bulk.registry import restricted_attrs

    hidden = restricted_attrs("member_profiles", access.privileges_for(db, user))
    if not hidden:
        return out
    if isinstance(out, list):
        return [_redact_one(o, hidden) for o in out]
    return _redact_one(out, hidden)


def _redact_one(o, hidden: set[str]):
    return o.model_copy(update={k: None for k in hidden if k in type(o).model_fields})


def _get(db: DB, member_id: int) -> MemberProfile:
    m = db.get(MemberProfile, member_id)
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
        DuplicateHit(id=m.id, mtr_id=m.mtr_id, name=m.display_name, matched_on=why)
        for m, why in service.find_duplicates(db, payload.name, payload.phone, payload.email, payload.exclude_id)
    ]


@router.get("/{member_id}")
def get_member(member_id: int, db: DB, user: CurrentUser) -> MemberDetail:
    access.require_privilege(db, user, "members.view")
    return _redact(db, user, _detail(db, _get(db, member_id)))


def _apply(db: DB, m: MemberProfile, data: dict) -> None:
    data = {k: (v.strip() if isinstance(v, str) else v) for k, v in data.items()}
    data = {k: (None if v == "" else v) for k, v in data.items()}
    if "email" in data and data["email"]:
        data["email"] = data["email"].lower()
    mtr_id = data.get("mtr_id")
    if mtr_id:
        clash = db.scalar(select(MemberProfile).where(MemberProfile.mtr_id == mtr_id, MemberProfile.id != (m.id or -1)))
        if clash is not None:
            raise HTTPException(status.HTTP_409_CONFLICT, f"MTR ID {mtr_id} is already {clash.display_name}'s")
    for k, v in data.items():
        setattr(m, k, v)
    # a roster email that belongs to an existing, unlinked account links them
    if m.user_id is None and m.email:
        account = db.scalar(select(User).where(User.email == m.email))
        if account is not None and account.profile is None:
            m.user_id = account.id


@router.post("", status_code=status.HTTP_201_CREATED)
def create_member(payload: MemberIn, db: DB, user: CurrentUser) -> MemberDetail:
    access.require_privilege(db, user, "members.edit")
    data = payload.model_dump(exclude_unset=True)
    if not (data.get("full_name") or "").strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A member needs a name")
    m = MemberProfile()
    if not data.get("mtr_id"):
        data["mtr_id"] = next_mtr_id(db)
    data.setdefault("data_confidence", "manual")
    data.setdefault("source_records", 1)
    _apply(db, m, data)
    db.add(m)
    db.flush()
    audit_log(db, user.id, "members", "created", "member", m.id, {"name": m.display_name, "mtr_id": m.mtr_id})
    db.commit()
    db.refresh(m)
    return _detail(db, m)


@router.patch("/{member_id}")
def update_member(member_id: int, payload: MemberIn, db: DB, user: CurrentUser) -> MemberDetail:
    access.require_privilege(db, user, "members.edit")
    m = _get(db, member_id)
    _apply(db, m, payload.model_dump(exclude_unset=True))
    audit_log(db, user.id, "members", "updated", "member", m.id, {"name": m.display_name})
    db.commit()
    db.refresh(m)
    return _detail(db, m)


@router.delete("/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_member(member_id: int, db: DB, user: CurrentUser) -> None:
    """Remove a roster-only member (e.g. a duplicate). Members with a portal
    account are retired by deactivating the account instead."""
    access.require_privilege(db, user, "members.edit")
    m = _get(db, member_id)
    if m.user_id is not None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "This member has a portal account — deactivate the account in User Management instead",
        )
    audit_log(db, user.id, "members", "deleted", "member", m.id, {"name": m.display_name, "mtr_id": m.mtr_id})
    db.delete(m)
    db.commit()
