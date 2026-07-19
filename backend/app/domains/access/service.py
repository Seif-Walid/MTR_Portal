"""Discord-style access ladder: the privilege vocabulary is fixed in code
(it's the list of things the app can actually gate — same idea as the three
role-template events), while the levels themselves are data the admin edits
on the site. Nothing anywhere checks a job title or role name — the only
question this module answers is "does this person's effective level include
privilege X?"."""

import json

from fastapi import HTTPException, status as http_status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domains.access.models import AccessLevel
from app.domains.positions.models import Position, PositionOccupant
from app.domains.users.models import User

# The fixed vocabulary: (key, label) — labels feed the site's level editor so
# the frontend never hardcodes the list.
PRIVILEGES: list[tuple[str, str]] = [
    ("inventory.view", "View inventory"),
    ("inventory.request", "Request items"),
    ("inventory.approve", "Approve & move stock"),
    ("inventory.edit", "Edit inventory"),
    ("competitions.view", "View competitions"),
    ("competitions.manage_seated", "Manage competitions where seated"),
    ("competitions.create", "Create competitions"),
    ("competitions.manage_any", "Manage any competition"),
    ("tasks.use", "Use tasks"),
    ("tasks.assign", "Assign tasks"),
    ("org.view", "View organization"),
    ("org.edit", "Edit organization"),
    ("people.view", "View team & directory"),
    ("users.manage", "Manage users"),
    ("audit.view", "View audit log"),
    ("sync.export", "Export to Sheets"),
    ("sync.rebuild", "Rebuild from Sheets"),
]

ALL_PRIVILEGE_KEYS: set[str] = {key for key, _ in PRIVILEGES}

# The starting ladder, shipped as data (created by the migration on real
# databases and by ensure_preset_levels for fresh/test ones). Rank 1 stores
# every key for transparency, though privileges_of grants it everything
# regardless.
PRESET_LEVELS: list[tuple[int, str, list[str]]] = [
    (1, "Admin", sorted(ALL_PRIVILEGE_KEYS)),
    (2, "Board", sorted(ALL_PRIVILEGE_KEYS - {"users.manage", "sync.rebuild"})),
    (3, "Lead", [
        "inventory.view", "inventory.request", "inventory.approve", "inventory.edit",
        "competitions.view", "competitions.manage_seated", "competitions.create",
        "tasks.use", "tasks.assign", "org.view", "people.view",
    ]),
    (4, "Member", [
        "inventory.view", "inventory.request",
        "competitions.view", "tasks.use", "org.view", "people.view",
    ]),
    (5, "Guest", []),
]


def ensure_preset_levels(db: Session) -> None:
    """Creates the starting ladder if no levels exist yet (fresh DB, tests)."""
    if db.scalar(select(AccessLevel.id).limit(1)) is not None:
        return
    for rank, name, keys in PRESET_LEVELS:
        db.add(AccessLevel(rank=rank, name=name, privileges=json.dumps(keys)))
    db.flush()


def list_levels(db: Session) -> list[AccessLevel]:
    return list(db.scalars(select(AccessLevel).order_by(AccessLevel.rank)))


def top_rank(db: Session) -> int | None:
    return db.scalar(select(AccessLevel.rank).order_by(AccessLevel.rank))


def bottom_level(db: Session) -> AccessLevel | None:
    return db.scalar(select(AccessLevel).order_by(AccessLevel.rank.desc()).limit(1))


def privileges_of(db: Session, level: AccessLevel | None) -> set[str]:
    """The rank-1 (top) level always has everything — an admin can't toggle
    themselves out of the controls."""
    if level is None:
        return set()
    if level.rank == top_rank(db):
        return set(ALL_PRIVILEGE_KEYS)
    return level.privilege_keys & ALL_PRIVILEGE_KEYS


def seat_levels(db: Session, user_id: int) -> list[AccessLevel]:
    """Levels of every org seat the user occupies (real or role-template)."""
    return list(db.scalars(
        select(AccessLevel)
        .join(Position, Position.access_level_id == AccessLevel.id)
        .join(PositionOccupant, PositionOccupant.position_id == Position.id)
        .where(PositionOccupant.user_id == user_id)
        .distinct()
    ))


def effective_level(db: Session, user: User) -> AccessLevel | None:
    """Strongest of: the user's personal override + every occupied seat's
    level. With neither, the bottom-most level applies — that's the ladder's
    default tier ("guests"), so toggling a privilege onto the bottom level
    grants it to everyone signed in."""
    candidates = seat_levels(db, user.id)
    if user.access_level_id is not None:
        override = db.get(AccessLevel, user.access_level_id)
        if override is not None:
            candidates.append(override)
    if candidates:
        return min(candidates, key=lambda lvl: lvl.rank)
    return bottom_level(db)


def privileges_for(db: Session, user: User) -> set[str]:
    return privileges_of(db, effective_level(db, user))


def has_privilege(db: Session, user: User, key: str) -> bool:
    return key in privileges_for(db, user)


def require_privilege(db: Session, user: User, key: str) -> None:
    if not has_privilege(db, user, key):
        raise HTTPException(
            http_status.HTTP_403_FORBIDDEN,
            "Your access level does not allow this",
        )


def is_top(db: Session, user: User) -> bool:
    """Effective level is the ladder's top — replaces the old is_admin
    bypasses (top level ignores structural limits like the task subtree)."""
    level = effective_level(db, user)
    return level is not None and level.rank == top_rank(db)


def effective_levels_bulk(db: Session, user_ids: list[int]) -> dict[int, AccessLevel | None]:
    """effective_level for many users in three queries — for list endpoints
    that need every user's level without an N+1."""
    levels = {lvl.id: lvl for lvl in list_levels(db)}
    fallback = min(levels.values(), key=lambda lvl: -lvl.rank) if levels else None
    candidates: dict[int, list[AccessLevel]] = {uid: [] for uid in user_ids}
    for uid, level_id in db.execute(
        select(PositionOccupant.user_id, Position.access_level_id)
        .join(Position, Position.id == PositionOccupant.position_id)
        .where(PositionOccupant.user_id.in_(user_ids), Position.access_level_id.is_not(None))
    ):
        candidates[uid].append(levels[level_id])
    for uid, override_id in db.execute(
        select(User.id, User.access_level_id).where(
            User.id.in_(user_ids), User.access_level_id.is_not(None)
        )
    ):
        if override_id in levels:
            candidates[uid].append(levels[override_id])
    return {
        uid: (min(found, key=lambda lvl: lvl.rank) if found else fallback)
        for uid, found in candidates.items()
    }


def users_with_privilege(db: Session, key: str) -> set[int]:
    """IDs of active users whose effective level includes the privilege."""
    ids = list(db.scalars(select(User.id).where(User.is_active)))
    by_user = effective_levels_bulk(db, ids)
    return {uid for uid, lvl in by_user.items() if key in privileges_of(db, lvl)}


# --- lockout guards ---------------------------------------------------------
def _top_override_user_ids(db: Session) -> set[int]:
    """Active users whose *personal override* is the top level — the safety
    anchors. Seats can also confer the top level, but a seat can be deleted
    by org edits; the override is what we refuse to orphan."""
    rank1 = db.scalar(select(AccessLevel).order_by(AccessLevel.rank).limit(1))
    if rank1 is None:
        return set()
    return set(db.scalars(
        select(User.id).where(User.access_level_id == rank1.id, User.is_active)
    ))


def assert_not_last_top_override(db: Session, user_id: int) -> None:
    """Raises if removing/downgrading this user's override (or deactivating
    them) would leave nobody holding a top-level override."""
    anchors = _top_override_user_ids(db)
    if anchors == {user_id}:
        raise HTTPException(
            http_status.HTTP_400_BAD_REQUEST,
            "At least one active user must keep a top-level override — assign it to "
            "someone else first.",
        )
