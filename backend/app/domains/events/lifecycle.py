"""Archiving and reactivating an event — the one place both happen, whichever
endpoint asks (the Events page's status edit or the Archive's Reactivate).

Archiving takes the event's role seats off the org chart (the chart only shows
active work), but first copies who sat in them into EventSeatRecord, so the
archive keeps the event's PMs, coaches, leads and seat-held rosters.
Reactivating rebuilds the seats from the current templates and seats those
people back where they were."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domains.events.models import Event, EventSeatRecord, EventStatus, tree_order
from app.domains.events.role_sync import (
    lineage_for_event,
    lineage_for_membership,
    lineage_for_team,
)
from app.domains.positions import role_engine
from app.domains.positions.models import Position, PositionOccupant
from app.domains.positions.service import resync_managers


def _names(comp: Event, **extra: str) -> dict[str, str]:
    return {"event": comp.name, "competition": comp.name, **extra}


def record_seats(db: Session, comp: Event) -> None:
    """Copy every occupant of the event's event- and team-level role seats into
    EventSeatRecord. Idempotent: a person already recorded in a seat is not
    recorded twice (a re-archived event keeps whatever couldn't be restored)."""
    team_ids = [t.id for cat in comp.categories for t in cat.teams]
    seats = list(db.scalars(
        select(Position).where(
            Position.role_template_id.is_not(None),
            ((Position.entity_type == "event") & (Position.entity_id == comp.id))
            | ((Position.entity_type == "team") & Position.entity_id.in_(team_ids)),
        )
    ))
    have = {
        (r.role_template_id, r.entity_type, r.entity_id, r.user_id)
        for r in db.scalars(select(EventSeatRecord).where(EventSeatRecord.event_id == comp.id))
    }
    for pos in seats:
        template = pos.role_template
        role = role_engine.role_name(template.title_template) if template else ""
        for link in pos.occupant_links:
            key = (pos.role_template_id, pos.entity_type, pos.entity_id, link.user_id)
            if key in have:
                continue
            have.add(key)
            db.add(EventSeatRecord(
                event_id=comp.id,
                team_id=pos.entity_id if pos.entity_type == "team" else None,
                role_template_id=pos.role_template_id,
                entity_type=pos.entity_type,
                entity_id=pos.entity_id,
                role=role or pos.title,
                user_id=link.user_id,
                user_name=link.user.full_name,
                sort_order=(template.sort_order if template and template.sort_order is not None else 0),
            ))
    db.flush()


def restore_seats(db: Session, comp: Event) -> None:
    """Seat each recorded person back into the rebuilt seat they held, and drop
    the record once they're there — the live seat is the truth again. Records
    whose seat no longer exists (its template was removed, its team deleted)
    or whose person is gone stay on the event's record."""
    for record in list(db.scalars(select(EventSeatRecord).where(EventSeatRecord.event_id == comp.id))):
        if record.role_template_id is None or record.entity_type is None or record.user_id is None:
            continue
        pos = role_engine.get_role_position(db, record.role_template_id, record.entity_type, record.entity_id)
        if pos is None:
            continue
        if record.user_id not in {link.user_id for link in pos.occupant_links}:
            db.add(PositionOccupant(position_id=pos.id, user_id=record.user_id))
            db.flush()
            db.expire(pos, ["occupants", "occupant_links"])
        db.delete(record)
    db.flush()


def _delete_seats(db: Session, comp: Event) -> None:
    for cat in comp.categories:
        for team in cat.teams:
            for member in team.members:
                role_engine.delete_positions_for_entity(db, "membership", member.id)
            role_engine.delete_positions_for_entity(db, "team", team.id)
    role_engine.delete_positions_for_entity(db, "event", comp.id)


def archive_event(db: Session, comp: Event) -> None:
    """Archive: record the seats' people, then take the seats off the chart."""
    comp.status = EventStatus.ARCHIVED
    # a finished event no longer recruits on the website
    comp.applications_open = False
    record_seats(db, comp)
    _delete_seats(db, comp)
    resync_managers(db)


def remove_event_seats(db: Session, comp: Event) -> None:
    """Take every seat off the chart without recording it — for deleting the
    event outright, which takes its record with it."""
    _delete_seats(db, comp)


def reactivate_event(db: Session, comp: Event) -> None:
    """Back to active: rebuild every seat from whatever templates exist now
    (member seats re-fill from the memberships), then put the recorded people
    back into theirs."""
    comp.status = EventStatus.ACTIVE
    role_engine.apply_event(
        db, event="event_created", entity_type="event", entity_id=comp.id,
        lineage=lineage_for_event(comp), names=_names(comp), kind_id=comp.kind_id,
    )
    for cat in comp.categories:
        for team in tree_order(cat.teams):  # parents first: sub-team seats nest under theirs
            if team.deleted_at is not None:
                continue
            names = _names(comp, team=team.name)
            role_engine.apply_event(
                db, event="team_created", entity_type="team", entity_id=team.id,
                lineage=lineage_for_team(comp, team.id), names=names, kind_id=comp.kind_id,
                nest_in_id=team.parent_team_id,
            )
            for member in team.members:
                role_engine.apply_event(
                    db, event="team_member_added", entity_type="membership",
                    entity_id=member.id,
                    lineage=lineage_for_membership(comp, team.id, member.id),
                    names={**names, "member": member.user.full_name},
                    kind_id=comp.kind_id, member_id=member.user_id,
                )
    restore_seats(db, comp)
    resync_managers(db)
