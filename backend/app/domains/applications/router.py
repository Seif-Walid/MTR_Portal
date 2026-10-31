"""Join applications from the website, for the people who recruit. Reading
them is gated by members.view (they're the same kind of personal data as the
roster); changing status/notes and adding an applicant to the roster by
members.edit. The website itself posts through /public/applications."""

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.domains.access import service as access
from app.domains.applications import service
from app.domains.applications.models import Application, ApplicationStatus
from app.domains.applications.schemas import ApplicationOut, ApplicationPatch, RosterMatch
from app.domains.audit.service import log as audit_log
from app.domains.auth.deps import DB, CurrentUser
from app.domains.users.models import MemberProfile
from app.domains.users.roster import next_mtr_id

router = APIRouter(prefix="/applications", tags=["applications"])


def _utc(d: datetime | None) -> datetime | None:
    # SQLite hands timestamps back naive; they are stored in UTC
    return d.replace(tzinfo=timezone.utc) if d is not None and d.tzinfo is None else d


def _out(a: Application, index) -> ApplicationOut:
    return ApplicationOut(
        id=a.id,
        full_name=a.full_name,
        email=a.email,
        phone=a.phone,
        school=a.school,
        year=a.year,
        subteam=a.subteam,
        motivation=a.motivation,
        event_id=a.event_id,
        event_name=a.event.name if a.event else None,
        status=a.status,
        notes=a.notes,
        member_id=a.member_id,
        member_mtr_id=a.member.mtr_id if a.member else None,
        reviewed_by=a.reviewed_by.full_name if a.reviewed_by else None,
        reviewed_at=_utc(a.reviewed_at),
        created_at=_utc(a.created_at),
        updated_at=_utc(a.updated_at),
        roster_matches=[
            RosterMatch(id=m.id, mtr_id=m.mtr_id, name=m.display_name, matched_on=why)
            for m, why in service.roster_matches(a, index)
        ],
    )


def _get(db: DB, application_id: int) -> Application:
    a = db.get(Application, application_id)
    if a is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Application not found")
    return a


@router.get("")
def list_applications(db: DB, user: CurrentUser) -> list[ApplicationOut]:
    access.require_privilege(db, user, "members.view")
    index = service.roster_index(db)
    rows = db.scalars(select(Application).order_by(Application.created_at.desc()))
    return [_out(a, index) for a in rows]


@router.patch("/{application_id}")
def update_application(application_id: int, payload: ApplicationPatch, db: DB, user: CurrentUser) -> ApplicationOut:
    access.require_privilege(db, user, "members.edit")
    a = _get(db, application_id)
    data = payload.model_dump(exclude_unset=True)
    if "notes" in data:
        a.notes = (data["notes"] or "").strip() or None
    if data.get("status") is not None and data["status"] != a.status:
        audit_log(db, user.id, "applications", "status", "application", a.id,
                  {"name": a.full_name, "from": a.status, "to": data["status"]})
        a.status = data["status"]
        a.reviewed_by_id = user.id
        a.reviewed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(a)
    return _out(a, service.roster_index(db))


@router.post("/{application_id}/add-to-roster")
def add_to_roster(application_id: int, db: DB, user: CurrentUser) -> ApplicationOut:
    """Accept the applicant onto the roster. Someone already on it by email or
    phone is linked rather than added twice; otherwise a new roster member is
    created with the next MTR ID and the application's contact details."""
    access.require_privilege(db, user, "members.edit")
    a = _get(db, application_id)
    if a.member_id is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "This applicant is already on the roster")
    matches = service.roster_matches(a, service.roster_index(db))
    if len(matches) > 1:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Several roster members share this email or phone — sort them out in Members first",
        )
    if matches:
        m = matches[0][0]
        action = "linked"
    else:
        m = MemberProfile(
            mtr_id=next_mtr_id(db),
            full_name=a.full_name,
            email=a.email,
            phone=a.phone,
            university=a.school,
            joined_at=datetime.now(timezone.utc),
            data_confidence="manual",
            source_records=1,
        )
        db.add(m)
        db.flush()
        audit_log(db, user.id, "members", "created", "member", m.id,
                  {"name": m.display_name, "mtr_id": m.mtr_id, "from_application": a.id})
        action = "added"
    a.member_id = m.id
    if a.status != ApplicationStatus.ACCEPTED:
        a.status = ApplicationStatus.ACCEPTED
        a.reviewed_by_id = user.id
        a.reviewed_at = datetime.now(timezone.utc)
    audit_log(db, user.id, "applications", action, "application", a.id,
              {"name": a.full_name, "member_id": m.id, "mtr_id": m.mtr_id})
    db.commit()
    db.refresh(a)
    return _out(a, service.roster_index(db))
