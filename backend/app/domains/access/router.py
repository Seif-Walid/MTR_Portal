import json

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select, update

from app.domains.access import service as access
from app.domains.access.models import AccessLevel
from app.domains.access.schemas import LevelCreate, LevelEdit, LevelOut, PrivilegeOut
from app.domains.audit.service import log as audit_log
from app.domains.auth.deps import DB, CurrentUser
from app.domains.positions.models import Position, RoleTemplate
from app.domains.users.models import User

router = APIRouter(prefix="/access", tags=["access"])


@router.get("/privileges")
def list_privileges(db: DB, user: CurrentUser) -> list[PrivilegeOut]:
    """The fixed vocabulary, with labels — feeds the level editor so the
    frontend never hardcodes it."""
    return [PrivilegeOut(key=key, label=label) for key, label in access.PRIVILEGES]


def _level_out(db: DB, level: AccessLevel) -> LevelOut:
    return LevelOut(
        id=level.id, rank=level.rank, name=level.name,
        privileges=sorted(access.privileges_of(db, level)),
        is_top=level.rank == access.top_rank(db),
    )


@router.get("/levels")
def list_levels(db: DB, user: CurrentUser) -> list[LevelOut]:
    """Readable by anyone signed in — pickers (position forms, user forms)
    need the ladder; editing it is users.manage."""
    return [_level_out(db, lvl) for lvl in access.list_levels(db)]


def _validate_privileges(keys: list[str]) -> list[str]:
    unknown = set(keys) - access.ALL_PRIVILEGE_KEYS
    if unknown:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"Unknown privileges: {', '.join(sorted(unknown))}"
        )
    return sorted(set(keys))


def _renumber(db: DB, ordered_ids: list[int]) -> None:
    """Two-phase renumber (negative staging first) — same unique-constraint
    collision avoidance as role-template sort_order."""
    by_id = {lvl.id: lvl for lvl in db.scalars(select(AccessLevel))}
    for i, lid in enumerate(ordered_ids, start=1):
        by_id[lid].rank = -i
    db.flush()
    for i, lid in enumerate(ordered_ids, start=1):
        by_id[lid].rank = i


@router.post("/levels", status_code=status.HTTP_201_CREATED)
def create_level(payload: LevelCreate, db: DB, user: CurrentUser) -> LevelOut:
    access.require_privilege(db, user, "users.manage")
    keys = _validate_privileges(payload.privileges)
    max_rank = max((lvl.rank for lvl in access.list_levels(db)), default=0)
    level = AccessLevel(rank=max_rank + 1, name=payload.name, privileges=json.dumps(keys))
    db.add(level)
    db.flush()
    if payload.rank is not None:
        ordered = [lvl.id for lvl in access.list_levels(db) if lvl.id != level.id]
        index = max(0, min(payload.rank - 1, len(ordered)))
        ordered.insert(index, level.id)
        _renumber(db, ordered)
    audit_log(db, user.id, "access", "level_created", "access_level", level.id,
              {"name": level.name})
    db.commit()
    db.refresh(level)
    return _level_out(db, level)


@router.patch("/levels/{level_id}")
def edit_level(level_id: int, payload: LevelEdit, db: DB, user: CurrentUser) -> LevelOut:
    access.require_privilege(db, user, "users.manage")
    level = db.get(AccessLevel, level_id)
    if level is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Level not found")
    if payload.name is not None and payload.name != level.name:
        audit_log(db, user.id, "access", "level_renamed", "access_level", level.id,
                  {"before": level.name, "after": payload.name})
        level.name = payload.name
    if payload.privileges is not None:
        if level.rank == access.top_rank(db):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "The top level always holds every privilege — it can't be edited.",
            )
        keys = _validate_privileges(payload.privileges)
        if set(keys) != level.privilege_keys:
            audit_log(db, user.id, "access", "level_privileges_changed", "access_level",
                      level.id, {"name": level.name, "privileges": keys})
        level.privileges = json.dumps(keys)
    if payload.rank is not None:
        ordered = [lvl.id for lvl in access.list_levels(db) if lvl.id != level_id]
        index = max(0, min(payload.rank - 1, len(ordered)))
        ordered.insert(index, level_id)
        _renumber(db, ordered)
    db.commit()
    db.refresh(level)
    return _level_out(db, level)


@router.delete("/levels/{level_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_level(level_id: int, db: DB, user: CurrentUser) -> None:
    access.require_privilege(db, user, "users.manage")
    level = db.get(AccessLevel, level_id)
    if level is None:
        return
    if level.rank == access.top_rank(db):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "The top level can't be deleted — someone must hold admin power.",
        )
    # references fall back to "no level" (confers/grants nothing)
    db.execute(update(User).where(User.access_level_id == level_id).values(access_level_id=None))
    db.execute(update(Position).where(Position.access_level_id == level_id).values(access_level_id=None))
    db.execute(update(RoleTemplate).where(RoleTemplate.access_level_id == level_id).values(access_level_id=None))
    audit_log(db, user.id, "access", "level_deleted", "access_level", level.id,
              {"name": level.name})
    db.delete(level)
    db.flush()
    _renumber(db, [lvl.id for lvl in access.list_levels(db)])
    db.commit()
