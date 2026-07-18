"""The competitions domain's knowledge of how role-template positions chain
across its own entity tree (competition -> team -> membership) — kept out of
positions/role_engine.py, which stays entirely generic. See
app/domains/positions/role_engine.py for the primitives this builds on."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domains.competitions.models import Competition
from app.domains.positions import role_engine


def lineage_for_competition(comp: Competition) -> dict[str, int]:
    return {"competition": comp.id}


def lineage_for_team(comp: Competition, team_id: int) -> dict[str, int]:
    return {"competition": comp.id, "team": team_id}


def lineage_for_membership(comp: Competition, team_id: int, membership_id: int) -> dict[str, int]:
    return {"competition": comp.id, "team": team_id, "membership": membership_id}


def resync_all(db: Session) -> None:
    """Walk every competition -> team -> membership and re-derive each
    existing role position's parent — call after any role-template CRUD that
    could change the chain topology (reorder, delete)."""
    for comp in db.scalars(select(Competition)):
        comp_lineage = lineage_for_competition(comp)
        role_engine.resync_position_parent(
            db, entity_type="competition", entity_id=comp.id, lineage=comp_lineage
        )
        for cat in comp.categories:
            for team in cat.teams:
                team_lineage = lineage_for_team(comp, team.id)
                role_engine.resync_position_parent(
                    db, entity_type="team", entity_id=team.id, lineage=team_lineage
                )
                for member in team.members:
                    role_engine.resync_position_parent(
                        db, entity_type="membership", entity_id=member.id,
                        lineage=lineage_for_membership(comp, team.id, member.id),
                    )
