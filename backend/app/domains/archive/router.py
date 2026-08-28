"""The archive: the portal's record of past (archived) events, and the source of
truth for everything the public website shows about them.

The archived-events *list* is open to every authenticated member — there is no
privilege gate, unlike the live Events domain.

Drilling into an event returns two things:

  * the **record** — the event's full roster (teams, their placements, their
    members and competition roles) plus its awards and official title. This is
    the same projection the website reads from /api/public/hall-of-fame, so what
    the site publishes is visible — and editable — here.
  * the viewer's **own participation** — the teams they were on and every task
    they held, tagged accomplished or incomplete. Personalized: it never shows
    anyone else's tasks.

Editing the record is gated on the same privilege as reactivating: archiving
tears down the managing seats, so seat-based management no longer applies.
"""

from datetime import date

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.domains.auth.deps import DB, CurrentUser
from app.domains.events.hall_of_fame import archived_competitions, event_groups, summary
from app.domains.events.models import (
    Event,
    EventCategory,
    EventStatus,
    EventTeam,
    EventTeamMember,
)
from app.domains.access import service as access
from app.domains.tasks.models import Task, TaskStatus
from app.domains.tasks.schemas import TaskOut

router = APIRouter(prefix="/archive", tags=["archive"])


class ArchivedEventOut(BaseModel):
    id: int
    name: str
    # Official long-form title ("MATE ROV Competition"), NULL when `name` is the
    # only name. The website heads each Hall-of-Fame record with it.
    full_name: str | None = None
    kind_name: str | None
    kind_label: str | None
    start_date: date | None
    end_date: date | None
    # Event-wide placements, e.g. ["🥇 1st Place — Sumo 1"].
    awards: list[str] | None = None
    can_manage: bool = False  # for the current viewer — gates Reactivate and edits


class ArchivedMemberOut(BaseModel):
    id: int  # the membership row, for editing the role in place
    name: str
    role: str | None = None


class ArchivedGroupOut(BaseModel):
    id: int  # the team row, for editing the placement in place
    label: str
    sublabel: str | None = None
    award: str | None = None
    members: list[ArchivedMemberOut] = []


class ArchivedTaskOut(BaseModel):
    outcome: str  # "accomplished" | "incomplete"
    team_name: str
    task: TaskOut


class ArchivedEventDetailOut(BaseModel):
    event: ArchivedEventOut
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


def _event_out(event: Event, can_manage: bool = False) -> ArchivedEventOut:
    return ArchivedEventOut(
        id=event.id,
        name=event.name,
        full_name=event.full_name,
        kind_name=event.kind.name if event.kind else None,
        kind_label=event.kind.event_label if event.kind else None,
        start_date=event.start_date,
        end_date=event.end_date,
        awards=event.awards or None,
        can_manage=can_manage,
    )


@router.get("/events")
def list_archived_events(db: DB, user: CurrentUser) -> list[ArchivedEventOut]:
    """Every archived event, newest first — public to all members."""
    events = db.scalars(
        select(Event)
        .where(Event.status == EventStatus.ARCHIVED)
        .order_by(Event.start_date.desc().nullslast(), Event.name)
    ).all()
    can = _can_manage_archive(db, user)
    return [_event_out(e, can) for e in events]


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
    longer applies. Reactivating — and correcting the historical record — is
    gated on the same privilege as creating an event (or the blanket
    manage-any)."""
    return access.has_privilege(db, user, "events.create") or access.has_privilege(
        db, user, "events.manage_any"
    )


def _require_manage(db: DB, user: CurrentUser) -> None:
    if not _can_manage_archive(db, user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed")


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
    event.status = EventStatus.ACTIVE
    db.commit()
    db.refresh(event)
    return _event_out(event, True)


@router.patch("/events/{event_id}")
def edit_archived_event(
    event_id: int, payload: ArchivedEventEdit, db: DB, user: CurrentUser
) -> ArchivedEventOut:
    """Correct an archived event's official title or awards without having to
    reactivate it first — the archive is the source the website reads."""
    _require_manage(db, user)
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
    return _event_out(event, True)


@router.patch("/teams/{team_id}")
def edit_archived_team(
    team_id: int, payload: ArchivedTeamEdit, db: DB, user: CurrentUser
) -> ArchivedGroupOut:
    """Set or clear one team's placement in an archived event."""
    _require_manage(db, user)
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
            "label": team.name,
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
    _require_manage(db, user)
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


@router.get("/events/{event_id}")
def archived_event_detail(event_id: int, db: DB, user: CurrentUser) -> ArchivedEventDetailOut:
    """The event's full roster, plus the viewer's own participation: the teams
    they were on and every task they held, tagged accomplished (approved) or
    incomplete."""
    event = db.get(Event, event_id)
    if event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Event not found")

    out_event = _event_out(event, _can_manage_archive(db, user))
    groups = [
        ArchivedGroupOut.model_validate(g) for g in event_groups(event, with_ids=True)
    ]

    # team_id -> name for every team in this event (incl. soft-deleted, so the
    # historical record stays complete)
    team_names: dict[int, str] = dict(
        db.execute(
            select(EventTeam.id, EventTeam.name)
            .join(EventCategory, EventTeam.category_id == EventCategory.id)
            .where(EventCategory.event_id == event_id)
        ).all()
    )
    if not team_names:
        return ArchivedEventDetailOut(event=out_event, groups=groups, teams=[], tasks=[])

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
    # tasks were scoped to, plus any explicit membership rows that persist.
    my_team_ids = {t.event_team_id for t in tasks if t.event_team_id in team_names}
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
    )
