"""The archive: the portal's record of past (archived) events, and the source of
truth for everything the public website shows about them.

The archived-events *list* is open to every authenticated member — there is no
privilege gate, unlike the live Events domain.

Drilling into an event returns two things:

  * the **record** — the event's full roster (teams, their placements, their
    members and competition roles) plus its awards and official title. This is
    the same projection the website reads from /api/public/hall-of-fame, so what
    the site publishes is visible — and editable — here. Alongside it, the
    event's **staff**: who held its role seats (PM, coach, lead, …) when it was
    archived, kept in EventSeatRecord because archiving takes the seats
    themselves off the org chart (see events/lifecycle.py).
  * the viewer's **own participation** — the teams they were on and every task
    they held, tagged accomplished or incomplete. Personalized: it never shows
    anyone else's tasks.

Once an event is over its record is history, so editing it — titles, awards,
placements, roles, staff — takes its own privilege, `archive.edit`: admin-only
by default, granted to any other level by toggling it in User Management.
Reactivating stays with whoever may create events.

The list is organized the way Events is: by event kind (Competition, Training,
R&D, whatever the admin adds), so a kind's archive sits apart from the others.
"""

from datetime import date

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.domains.auth.deps import DB, CurrentUser
from app.domains.events import lifecycle
from app.domains.events.hall_of_fame import archived_competitions, event_groups, summary
from app.domains.events.models import (
    Event,
    EventCategory,
    EventKind,
    EventSeatRecord,
    EventStatus,
    EventTeam,
    EventTeamMember,
)
from app.domains.access import service as access
from app.domains.tasks.models import Task, TaskStatus
from app.domains.tasks.schemas import TaskOut
from app.domains.users.models import User

router = APIRouter(prefix="/archive", tags=["archive"])


class ArchivedEventOut(BaseModel):
    id: int
    name: str
    # Official long-form title ("MATE ROV Competition"), NULL when `name` is the
    # only name. The website heads each Hall-of-Fame record with it.
    full_name: str | None = None
    kind_id: int | None = None
    kind_slug: str | None = None
    kind_name: str | None
    kind_label: str | None
    team_label: str | None = None
    member_label: str | None = None
    start_date: date | None
    end_date: date | None
    # Event-wide placements, e.g. ["🥇 1st Place — Sumo 1"].
    awards: list[str] | None = None
    can_manage: bool = False  # for the current viewer — gates Reactivate
    can_edit: bool = False  # for the current viewer — gates editing the record


class ArchivedMemberOut(BaseModel):
    id: int  # the membership row, for editing the role in place
    name: str
    role: str | None = None


class ArchivedStaffOut(BaseModel):
    """One person in one of the event's role seats, as recorded at archive."""

    id: int  # the EventSeatRecord row, for removing it
    role: str
    name: str
    user_id: int | None = None
    # Set only for a seat whose team is no longer in the roster (deleted
    # since), which is then listed with the event-wide staff.
    team: str | None = None


class ArchivedGroupOut(BaseModel):
    id: int  # the team row, for editing the placement in place
    label: str
    sublabel: str | None = None
    award: str | None = None
    members: list[ArchivedMemberOut] = []
    staff: list[ArchivedStaffOut] = []  # the team's role seats: coach, lead, …


class ArchivedTaskOut(BaseModel):
    outcome: str  # "accomplished" | "incomplete"
    team_name: str
    task: TaskOut


class ArchivedEventDetailOut(BaseModel):
    event: ArchivedEventOut
    staff: list[ArchivedStaffOut] = []  # event-wide seats, e.g. the PMs
    # The event record's own free-text staff fields (imported from the member
    # database), shown when present — some events only ever had these.
    mentors: str | None = None
    captains: str | None = None
    groups: list[ArchivedGroupOut]  # the whole roster — what the public site shows
    teams: list[str]  # the viewer's teams within this event
    tasks: list[ArchivedTaskOut]


class ArchivedEventEdit(BaseModel):
    """The Hall-of-Fame fields of an archived event. Each pair sets or clears."""

    full_name: str | None = Field(default=None, max_length=255)
    clear_full_name: bool = False
    awards: list[str] | None = None
    clear_awards: bool = False


class ArchivedTeamEdit(BaseModel):
    award: str | None = Field(default=None, max_length=255)
    clear_award: bool = False


class ArchivedMemberEdit(BaseModel):
    role: str | None = Field(default=None, max_length=100)
    clear_role: bool = False


class ArchivedStaffAdd(BaseModel):
    """Record someone in a role by hand — a portal account, or just a name."""

    role: str = Field(min_length=1, max_length=255)
    team_id: int | None = None  # NULL = an event-wide role
    user_id: int | None = None
    name: str | None = Field(default=None, max_length=255)


class ArchivedKindOut(BaseModel):
    """One event kind, as a section of the archive."""

    id: int
    slug: str
    name: str
    event_label: str
    count: int  # archived events of this kind


def _event_out(event: Event, can_manage: bool = False, can_edit: bool = False) -> ArchivedEventOut:
    return ArchivedEventOut(
        id=event.id,
        name=event.name,
        full_name=event.full_name,
        kind_id=event.kind_id,
        kind_slug=event.kind.slug if event.kind else None,
        kind_name=event.kind.name if event.kind else None,
        kind_label=event.kind.event_label if event.kind else None,
        team_label=event.kind.team_label if event.kind else None,
        member_label=event.kind.member_label if event.kind else None,
        start_date=event.start_date,
        end_date=event.end_date,
        awards=event.awards or None,
        can_manage=can_manage,
        can_edit=can_edit,
    )


@router.get("/kinds")
def list_archive_kinds(db: DB, user: CurrentUser) -> list[ArchivedKindOut]:
    """Every event kind in Events-tab order, with how many archived events it
    holds — the archive's sections. Public to all members."""
    counts = dict(
        db.execute(
            select(Event.kind_id, func.count())
            .where(Event.status == EventStatus.ARCHIVED)
            .group_by(Event.kind_id)
        ).all()
    )
    return [
        ArchivedKindOut(
            id=k.id, slug=k.slug, name=k.name, event_label=k.event_label, count=counts.get(k.id, 0)
        )
        for k in db.scalars(select(EventKind).order_by(EventKind.sort_order))
    ]


@router.get("/events")
def list_archived_events(
    db: DB, user: CurrentUser, kind_id: int | None = None
) -> list[ArchivedEventOut]:
    """Every archived event, newest first — public to all members. `kind_id`
    narrows it to one kind's section."""
    query = select(Event).where(Event.status == EventStatus.ARCHIVED)
    if kind_id is not None:
        query = query.where(Event.kind_id == kind_id)
    events = db.scalars(
        query.order_by(Event.start_date.desc().nullslast(), Event.name)
    ).all()
    can, edit = _can_manage_archive(db, user), _can_edit_archive(db, user)
    return [_event_out(e, can, edit) for e in events]


class ArchiveSummaryOut(BaseModel):
    """The headline the website prints above its Hall of Fame."""

    competitions: int
    seasons: int
    members_fielded: int
    gold: int
    silver: int
    bronze: int
    special: int  # judged awards that name no placement, e.g. Best Documentation


@router.get("/summary")
def archive_summary(db: DB, user: CurrentUser) -> ArchiveSummaryOut:
    """What the whole record adds up to — the same aggregate the public site
    shows, counted from the archived competitions rather than kept by hand."""
    return ArchiveSummaryOut(**summary(list(db.scalars(archived_competitions()).all())))


def _can_manage_archive(db: DB, user: CurrentUser) -> bool:
    """Archiving tears down every managing seat, so seat-based management no
    longer applies. Reactivating is gated on the same privilege as creating
    an event (or the blanket manage-any)."""
    return access.has_privilege(db, user, "events.create") or access.has_privilege(
        db, user, "events.manage_any"
    )


def _require_manage(db: DB, user: CurrentUser) -> None:
    if not _can_manage_archive(db, user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed")


def _can_edit_archive(db: DB, user: CurrentUser) -> bool:
    """A finished event's record is history — only levels granted
    archive.edit (the top level always has it) may correct it."""
    return access.has_privilege(db, user, "archive.edit")


def _require_edit(db: DB, user: CurrentUser) -> None:
    if not _can_edit_archive(db, user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Editing the archive is not allowed")


def _get_archived(db: DB, event_id: int) -> Event:
    event = db.get(Event, event_id)
    if event is None or event.status != EventStatus.ARCHIVED:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Archived event not found")
    return event


def _archived_team(db: DB, team_id: int) -> EventTeam:
    """A team belonging to an archived event — edits here never touch live ones,
    which keep their own seat-based permission rules."""
    team = db.get(EventTeam, team_id)
    if team is None or team.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Team not found")
    if team.category.event.status != EventStatus.ARCHIVED:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Team is not in an archived event")
    return team


@router.post("/events/{event_id}/reactivate")
def reactivate_event(event_id: int, db: DB, user: CurrentUser) -> ArchivedEventOut:
    """Move an archived event back to active — managers only."""
    event = _get_archived(db, event_id)
    _require_manage(db, user)
    # the same path as the Events page's status edit: the seats come back,
    # and the recorded people with them
    lifecycle.reactivate_event(db, event)
    db.commit()
    db.refresh(event)
    return _event_out(event, True, _can_edit_archive(db, user))


@router.patch("/events/{event_id}")
def edit_archived_event(
    event_id: int, payload: ArchivedEventEdit, db: DB, user: CurrentUser
) -> ArchivedEventOut:
    """Correct an archived event's official title or awards without having to
    reactivate it first — the archive is the source the website reads."""
    _require_edit(db, user)
    event = _get_archived(db, event_id)
    if payload.clear_full_name:
        event.full_name = None
    elif payload.full_name is not None:
        event.full_name = payload.full_name
    if payload.clear_awards:
        event.awards = None
    elif payload.awards is not None:
        event.awards = payload.awards
    db.commit()
    db.refresh(event)
    return _event_out(event, _can_manage_archive(db, user), True)


@router.patch("/teams/{team_id}")
def edit_archived_team(
    team_id: int, payload: ArchivedTeamEdit, db: DB, user: CurrentUser
) -> ArchivedGroupOut:
    """Set or clear one team's placement in an archived event."""
    _require_edit(db, user)
    team = _archived_team(db, team_id)
    if payload.clear_award:
        team.award = None
    elif payload.award is not None:
        team.award = payload.award
    db.commit()
    db.refresh(team)
    return ArchivedGroupOut.model_validate(
        {
            "id": team.id,
            "label": team.path_name,
            "sublabel": None if team.category.name == team.name else team.category.name,
            "award": team.award,
            "members": [
                {"id": m.id, "name": m.user.full_name, "role": m.role} for m in team.members
            ],
        }
    )


@router.patch("/members/{member_id}")
def edit_archived_member(
    member_id: int, payload: ArchivedMemberEdit, db: DB, user: CurrentUser
) -> ArchivedMemberOut:
    """Set or clear one member's competition role in an archived event."""
    _require_edit(db, user)
    member = db.get(EventTeamMember, member_id)
    if member is None or member.team.category.event.status != EventStatus.ARCHIVED:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Member not found")
    if payload.clear_role:
        member.role = None
    elif payload.role is not None:
        member.role = payload.role
    db.commit()
    db.refresh(member)
    return ArchivedMemberOut(id=member.id, name=member.user.full_name, role=member.role)


@router.post("/events/{event_id}/staff", status_code=status.HTTP_201_CREATED)
def add_archived_staff(
    event_id: int, payload: ArchivedStaffAdd, db: DB, user: CurrentUser
) -> ArchivedStaffOut:
    """Record who held a role in an archived event — how staff the event lost
    before archiving kept them gets put back."""
    _require_edit(db, user)
    event = _get_archived(db, event_id)
    team: EventTeam | None = None
    if payload.team_id is not None:
        team = _archived_team(db, payload.team_id)
        if team.category.event_id != event.id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "That team is not in this event")
    person = db.get(User, payload.user_id) if payload.user_id is not None else None
    if payload.user_id is not None and person is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "User not found")
    name = person.full_name if person else (payload.name or "").strip()
    if not name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Pick a person or type a name")
    record = EventSeatRecord(
        event_id=event.id, team_id=team.id if team else None,
        role=payload.role.strip(), user_id=person.id if person else None, user_name=name,
        # after every seat copied from the chart, in the order added
        sort_order=(db.scalar(
            select(func.max(EventSeatRecord.sort_order)).where(EventSeatRecord.event_id == event.id)
        ) or 0) + 1,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return _staff_out(record)


@router.delete("/staff/{record_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_archived_staff(record_id: int, db: DB, user: CurrentUser) -> None:
    _require_edit(db, user)
    record = db.get(EventSeatRecord, record_id)
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    _get_archived(db, record.event_id)
    db.delete(record)
    db.commit()


def _staff_out(record: EventSeatRecord, team: str | None = None) -> ArchivedStaffOut:
    return ArchivedStaffOut(
        id=record.id, role=record.role, name=record.user_name, user_id=record.user_id, team=team
    )


@router.get("/events/{event_id}")
def archived_event_detail(event_id: int, db: DB, user: CurrentUser) -> ArchivedEventDetailOut:
    """The event's full roster, plus the viewer's own participation: the teams
    they were on and every task they held, tagged accomplished (approved) or
    incomplete."""
    event = db.get(Event, event_id)
    if event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Event not found")

    out_event = _event_out(event, _can_manage_archive(db, user), _can_edit_archive(db, user))
    groups = [
        ArchivedGroupOut.model_validate(g) for g in event_groups(event, with_ids=True)
    ]

    # Staff: each recorded seat goes on its team's card, or event-wide when it
    # has no team — or its team is no longer on the roster.
    records = list(db.scalars(
        select(EventSeatRecord)
        .where(EventSeatRecord.event_id == event_id)
        .order_by(EventSeatRecord.sort_order, EventSeatRecord.id)
    ))
    by_team = {g.id: g for g in groups}
    event_staff: list[ArchivedStaffOut] = []
    for r in records:
        if r.team_id in by_team:
            by_team[r.team_id].staff.append(_staff_out(r))
        else:
            gone = db.get(EventTeam, r.team_id) if r.team_id is not None else None
            event_staff.append(_staff_out(r, gone.path_name if gone else None))
    record_fields = {"staff": event_staff, "mentors": event.mentors, "captains": event.captains}

    # team_id -> name for every team in this event (incl. soft-deleted, so the
    # historical record stays complete)
    team_names: dict[int, str] = {
        t.id: t.path_name
        for t in db.scalars(
            select(EventTeam)
            .join(EventCategory, EventTeam.category_id == EventCategory.id)
            .where(EventCategory.event_id == event_id)
        )
    }
    if not team_names:
        return ArchivedEventDetailOut(
            event=out_event, groups=groups, teams=[], tasks=[], **record_fields
        )

    tasks = list(
        db.scalars(
            select(Task)
            .where(
                Task.assignee_id == user.id,
                Task.event_team_id.in_(team_names.keys()),
            )
            .order_by(Task.updated_at.desc())
        ).unique()
    )

    # The viewer's teams in this event. Role seats are deleted when an event is
    # archived, so we reconstruct from the durable signals: the teams their
    # tasks were scoped to, the seats recorded for them, and any explicit
    # membership rows that persist.
    my_team_ids = {t.event_team_id for t in tasks if t.event_team_id in team_names}
    my_team_ids |= {r.team_id for r in records if r.user_id == user.id and r.team_id in team_names}
    my_team_ids |= set(
        db.scalars(
            select(EventTeamMember.team_id).where(
                EventTeamMember.user_id == user.id,
                EventTeamMember.team_id.in_(team_names.keys()),
            )
        )
    )

    out_tasks = [
        ArchivedTaskOut(
            outcome="accomplished" if t.status == TaskStatus.APPROVED else "incomplete",
            team_name=team_names.get(t.event_team_id, "—"),
            task=TaskOut.model_validate(t),
        )
        for t in tasks
    ]
    return ArchivedEventDetailOut(
        event=out_event,
        groups=groups,
        teams=sorted(team_names[tid] for tid in my_team_ids),
        tasks=out_tasks,
        **record_fields,
    )
