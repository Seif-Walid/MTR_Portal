"""The events domain's knowledge of how role-template positions chain
across its own entity tree (event -> team -> membership) — kept out of
positions/role_engine.py, which stays entirely generic. See
app/domains/positions/role_engine.py for the primitives this builds on."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domains.events.models import Event
from app.domains.positions import role_engine


def lineage_for_event(comp: Event) -> dict[str, int]:
    return {"event": comp.id}


def lineage_for_team(comp: Event, team_id: int) -> dict[str, int]:
    return {"event": comp.id, "team": team_id}


def lineage_for_membership(comp: Event, team_id: int, membership_id: int) -> dict[str, int]:
    return {"event": comp.id, "team": team_id, "membership": membership_id}


def resync_all(db: Session) -> None:
    """Walk every event -> team -> membership and re-derive each
    existing role position's parent — call after any role-template CRUD that
    could change the chain topology (reorder, delete). Each event's kind
    scopes which templates its positions chain against."""
    for comp in db.scalars(select(Event)):
        kind_id = comp.kind_id
        role_engine.resync_position_parent(
            db, entity_type="event", entity_id=comp.id,
            lineage=lineage_for_event(comp), kind_id=kind_id,
        )
        for cat in comp.categories:
            for team in cat.teams:
                role_engine.resync_position_parent(
                    db, entity_type="team", entity_id=team.id,
                    lineage=lineage_for_team(comp, team.id), kind_id=kind_id,
                )
                for member in team.members:
                    role_engine.resync_position_parent(
                        db, entity_type="membership", entity_id=member.id,
                        lineage=lineage_for_membership(comp, team.id, member.id), kind_id=kind_id,
                    )
