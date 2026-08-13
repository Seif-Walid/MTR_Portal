"""The public archive: a browsable record of past (archived) events.

The archived-events *list* is open to every authenticated member — there is no
privilege gate, unlike the live Events domain. Drilling into an event, however,
is deliberately *personalized*: it shows only the viewer's own tasks in that
event (what they accomplished vs. failed), never anyone else's.
"""

from datetime import date

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from app.domains.auth.deps import DB, CurrentUser
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
    kind_name: str | None
    kind_label: str | None
    start_date: date | None
    end_date: date | None
    can_manage: bool = False  # for the current viewer — gates Reactivate


class ArchivedTaskOut(BaseModel):
    outcome: str  # "accomplished" | "incomplete"
    team_name: str
    task: TaskOut


class ArchivedEventDetailOut(BaseModel):
    event: ArchivedEventOut
    teams: list[str]  # the viewer's teams within this event
    tasks: list[ArchivedTaskOut]


def _event_out(event: Event, can_manage: bool = False) -> ArchivedEventOut:
    return ArchivedEventOut(
        id=event.id,
        name=event.name,
        kind_name=event.kind.name if event.kind else None,
        kind_label=event.kind.event_label if event.kind else None,
        start_date=event.start_date,
        end_date=event.end_date,
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
    can = _can_reactivate(db, user)
    return [_event_out(e, can) for e in events]


def _can_reactivate(db: DB, user: CurrentUser) -> bool:
    """Archiving tears down every managing seat, so seat-based management no
    longer applies. Reactivation is gated on the same privilege as creating an
    event (or the blanket manage-any)."""
    return access.has_privilege(db, user, "events.create") or access.has_privilege(
        db, user, "events.manage_any"
    )


@router.post("/events/{event_id}/reactivate")
def reactivate_event(event_id: int, db: DB, user: CurrentUser) -> ArchivedEventOut:
    """Move an archived event back to active — managers only."""
    event = db.get(Event, event_id)
    if event is None or event.status != EventStatus.ARCHIVED:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Archived event not found")
    if not _can_reactivate(db, user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed")
    event.status = EventStatus.ACTIVE
    db.commit()
    db.refresh(event)
    return _event_out(event, True)


@router.get("/events/{event_id}")
def archived_event_detail(event_id: int, db: DB, user: CurrentUser) -> ArchivedEventDetailOut:
    """The viewer's own participation in one archived event: the teams they were
    on and every task they held, tagged accomplished (approved) or incomplete."""
    event = db.get(Event, event_id)
    if event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Event not found")

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
        return ArchivedEventDetailOut(event=_event_out(event), teams=[], tasks=[])

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
        event=_event_out(event),
        teams=sorted(team_names[tid] for tid in my_team_ids),
        tasks=out_tasks,
    )
