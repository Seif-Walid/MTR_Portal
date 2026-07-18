"""Generic, admin-configurable auto-seating: a RoleTemplate says "when X
happens, seat a position titled Y, chained under whatever role came before
it." This module knows nothing about competitions/teams/members specifically
— it operates on `event` (one of the three fixed trigger points the app
actually has) and `entity_type`/`entity_id` (whatever the caller says an
event happened to), so the competitions domain stays the only place that
knows what a competition/team/membership actually is. See
app/domains/positions/models.py for the exclusion rules these positions get
from the rest of the org-chart logic (resync_managers,
clear_user_from_other_positions)."""

from fastapi import HTTPException, status as http_status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domains.positions.models import Position, PositionOccupant, RoleChainRoot, RoleTemplate

# The three fixed points in the app that can seat someone, and the kind of
# entity each one produces a position for. Fixed because the app only has
# three such trigger points — not a hardcoded role name.
EVENT_ENTITY_TYPE = {
    "competition_created": "competition",
    "team_created": "team",
    "team_member_added": "membership",
}

# The entity types a *real* lineage would contain for each event, if every
# ancestor already exists — i.e. EVENT_ENTITY_TYPE, plus everything shallower
# in the fixed competition -> team -> membership structure. Used only to
# preview where a template *would* chain in the org tree before any real
# competition/team exists to compute an actual lineage from — see
# template_chain_parent_id.
_STRUCTURAL_LINEAGE = {
    "competition_created": {"competition"},
    "team_created": {"competition", "team"},
    "team_member_added": {"competition", "team", "membership"},
}


def template_chain_parent_id(templates: list[RoleTemplate], template: RoleTemplate) -> int | None:
    """Which other template this one would chain under, assuming every
    ancestor entity that *could* exist by the time this template's event
    fires actually does (the common case — see _find_chain_parent for the
    real, lineage-gated version used at seating time). None means it would
    resolve straight to root. Purely structural — no DB/position lookups —
    so it's cheap enough to compute for every template on every list call,
    for the org tree to preview the chain before anything real exists yet."""
    eligible_types = _STRUCTURAL_LINEAGE[template.event]
    for t in reversed([t for t in templates if t.sort_order < template.sort_order]):
        if EVENT_ENTITY_TYPE[t.event] in eligible_types:
            return t.id
    return None


class _SafeDict(dict):
    def __missing__(self, key: str) -> str:
        return ""


def _safe_title(template: str, names: dict[str, str]) -> str:
    return template.format_map(_SafeDict(names))


# --- template CRUD ----------------------------------------------------------
def list_templates(db: Session) -> list[RoleTemplate]:
    return list(db.scalars(select(RoleTemplate).order_by(RoleTemplate.sort_order)))


def has_templates(db: Session) -> bool:
    return db.scalar(select(RoleTemplate.id).limit(1)) is not None


def _renumber(db: Session, ordered_ids: list[int]) -> None:
    """Reassigns 1..N in the given order. Goes through a negative staging
    pass first — going straight to final values can collide mid-flush with
    the unique constraint on sort_order (e.g. swapping #1 and #2 directly
    would momentarily try to give two rows the same value, in whichever
    order the UPDATEs happen to be issued)."""
    by_id = {t.id: t for t in db.scalars(select(RoleTemplate))}
    for i, tid in enumerate(ordered_ids, start=1):
        by_id[tid].sort_order = -i
    db.flush()
    for i, tid in enumerate(ordered_ids, start=1):
        by_id[tid].sort_order = i


def create_template(
    db: Session, *, title_template: str, event: str,
    grants_management: bool = False, auto_assign_creator: bool = False,
    insert_after_id: int | None = None,
) -> RoleTemplate:
    """insert_after_id places the new template immediately after that one in
    the chain instead of at the end — used when the admin adds a role from an
    existing role's "+" in the org tree, so the new role is guaranteed to
    resolve under the exact node they clicked (appending could land it under
    a later same-event sibling instead). Ignored if the referenced template
    no longer exists."""
    if event not in EVENT_ENTITY_TYPE:
        raise HTTPException(http_status.HTTP_400_BAD_REQUEST, f"Unknown event '{event}'")
    next_order = (db.scalar(select(RoleTemplate.sort_order).order_by(RoleTemplate.sort_order.desc())) or 0) + 1
    template = RoleTemplate(
        title_template=title_template, event=event, sort_order=next_order,
        grants_management=grants_management, auto_assign_creator=auto_assign_creator,
    )
    db.add(template)
    db.flush()
    if insert_after_id is not None:
        ordered = [t.id for t in list_templates(db) if t.id != template.id]
        if insert_after_id in ordered:
            ordered.insert(ordered.index(insert_after_id) + 1, template.id)
            _renumber(db, ordered)
            db.flush()
    return template


def update_template(
    db: Session, template_id: int, *, title_template: str | None = None,
    grants_management: bool | None = None, auto_assign_creator: bool | None = None,
    new_sort_order: int | None = None,
) -> RoleTemplate:
    template = db.get(RoleTemplate, template_id)
    if template is None:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, "Role not found")
    if title_template is not None:
        template.title_template = title_template
    if grants_management is not None:
        template.grants_management = grants_management
    if auto_assign_creator is not None:
        template.auto_assign_creator = auto_assign_creator
    if new_sort_order is not None:
        ordered = [t.id for t in list_templates(db) if t.id != template_id]
        index = max(0, min(new_sort_order - 1, len(ordered)))
        ordered.insert(index, template_id)
        _renumber(db, ordered)
    db.flush()
    return template


def delete_template(db: Session, template_id: int) -> None:
    """Deletes the template and every position it produced (cascading to
    their occupants). Anything that was chained under one of those positions
    is left with a dangling parent_id — call competitions/role_sync.resync_all
    right after this to re-derive correct parents (it naturally splices the
    gap closed: the backward search just skips the now-missing template)."""
    template = db.get(RoleTemplate, template_id)
    if template is None:
        return
    for pos in db.scalars(select(Position).where(Position.role_template_id == template_id)):
        db.delete(pos)
    db.flush()
    db.delete(template)
    db.flush()
    _renumber(db, [t.id for t in list_templates(db)])


# --- root ---------------------------------------------------------------
def get_root(db: Session) -> RoleChainRoot | None:
    return db.scalar(select(RoleChainRoot))


def root_position_id(db: Session) -> int | None:
    root = get_root(db)
    return root.position_id if root else None


_root_position_id = root_position_id  # internal alias used below


def _remember_root(db: Session, position_id: int) -> None:
    root = get_root(db)
    if root is None:
        db.add(RoleChainRoot(id=1, position_id=position_id))
    elif root.position_id is None:
        root.position_id = position_id


# --- positions ------------------------------------------------------------
def get_role_position(db: Session, template_id: int, entity_type: str, entity_id: int) -> Position | None:
    return db.scalar(
        select(Position).where(
            Position.role_template_id == template_id,
            Position.entity_type == entity_type,
            Position.entity_id == entity_id,
        )
    )


def _find_chain_parent(db: Session, *, before_order: int, lineage: dict[str, int]) -> tuple[int | None, bool]:
    """Walks earlier-order templates looking for the nearest one that already
    has a position for an ancestor entity present in `lineage`. Returns
    (parent_id, blocked).

    blocked=True means at least one earlier template's event applies to this
    lineage (its entity type is present) but none of them have produced a
    position for it yet — the chain has a missing link (most commonly: that
    template was added *after* this entity already existed, so it was never
    backfilled). The caller must not create/keep a position here at all, not
    even parented at root — that would silently orphan it ahead of a link
    that's supposed to exist. This is also what makes a role "non-chaining":
    if nothing before it in sort_order is eligible for this lineage at all
    (blocked=False, parent_id=None), it always resolves straight to root
    instead of waiting on anything.

    parent_id is None with blocked=False when there's genuinely no earlier
    template that could ever apply to this lineage — the caller falls back
    to the shared root position."""
    templates = list_templates(db)
    saw_eligible = False
    for template in reversed([t for t in templates if t.sort_order < before_order]):
        want_entity_type = EVENT_ENTITY_TYPE[template.event]
        ancestor_id = lineage.get(want_entity_type)
        if ancestor_id is None:
            continue
        saw_eligible = True
        pos = get_role_position(db, template.id, want_entity_type, ancestor_id)
        if pos is not None:
            return pos.id, False
    return None, saw_eligible


def _seed_occupants(db: Session, position: Position, user_ids: list[int]) -> None:
    """Add-only — used right after creating a position, which has no
    occupants yet, so there's nothing to remove first."""
    for uid in user_ids:
        db.add(PositionOccupant(position_id=position.id, user_id=uid))
    if user_ids:
        db.flush()
        db.expire(position, ["occupants", "occupant_links"])


def apply_event(
    db: Session, *, event: str, entity_type: str, entity_id: int,
    lineage: dict[str, int], names: dict[str, str],
    creator_id: int | None = None, member_id: int | None = None,
    root_position_id: int | None = None,
) -> None:
    """Ensures a position exists for every template matching `event`, for
    this (entity_type, entity_id). Idempotent — a template that already has a
    position for this entity is left alone. A template whose chain has a
    missing link for this lineage (see _find_chain_parent) is skipped, not
    forced to root."""
    for template in list_templates(db):
        if template.event != event:
            continue
        if get_role_position(db, template.id, entity_type, entity_id) is not None:
            continue
        parent_id, blocked = _find_chain_parent(db, before_order=template.sort_order, lineage=lineage)
        if blocked:
            continue
        used_root = parent_id is None
        if used_root:
            parent_id = root_position_id if root_position_id is not None else _root_position_id(db)
            if parent_id is None:
                raise HTTPException(
                    http_status.HTTP_400_BAD_REQUEST,
                    "This is the first role position ever — pick where it goes in the org "
                    "chart (asked once; every later one reuses this).",
                )
        position = Position(
            title=_safe_title(template.title_template, names),
            parent_id=parent_id, is_technical=False,
            role_template_id=template.id, entity_type=entity_type, entity_id=entity_id,
        )
        db.add(position)
        db.flush()
        if used_root:
            _remember_root(db, parent_id)
        if event == "team_member_added" and member_id is not None:
            _seed_occupants(db, position, [member_id])
        elif template.auto_assign_creator and creator_id is not None:
            _seed_occupants(db, position, [creator_id])


def retitle_positions_for_entity(db: Session, entity_type: str, entity_id: int, names: dict[str, str]) -> None:
    for pos in db.scalars(
        select(Position).where(Position.entity_type == entity_type, Position.entity_id == entity_id)
    ):
        pos.title = _safe_title(pos.role_template.title_template, names)


def vacate_positions_for_entity(db: Session, entity_type: str, entity_id: int) -> None:
    positions = list(db.scalars(
        select(Position).where(Position.entity_type == entity_type, Position.entity_id == entity_id)
    ))
    for pos in positions:
        for link in list(pos.occupant_links):
            db.delete(link)
    db.flush()
    # `occupants` (a separate viewonly secondary-join relationship over the
    # same position_occupants rows) doesn't get invalidated by deleting
    # through `occupant_links` — same two-relationships-one-truth trap as
    # set_position_occupants above, just easy to miss on the "many
    # positions at once" cascade path.
    for pos in positions:
        db.expire(pos, ["occupants", "occupant_links"])


def delete_positions_for_entity(db: Session, entity_type: str, entity_id: int) -> None:
    for pos in db.scalars(
        select(Position).where(Position.entity_type == entity_type, Position.entity_id == entity_id)
    ):
        db.delete(pos)
    db.flush()


def resync_position_parent(db: Session, *, entity_type: str, entity_id: int, lineage: dict[str, int]) -> None:
    """Re-derive parent_id for this entity's own role positions from the
    current template chain — call after a template's order changes or a
    template is deleted, once per (entity_type, entity_id) that has any role
    positions (see competitions/role_sync.resync_all for the tree walk).

    A position whose chain link is now missing (see _find_chain_parent) is
    left exactly where it last resolved rather than deleted or moved — this
    only re-derives *existing* positions' parents, it never removes seats a
    real person may be occupying just because a later edit elsewhere broke
    the chain above them."""
    for pos in db.scalars(
        select(Position).where(Position.entity_type == entity_type, Position.entity_id == entity_id)
    ):
        if pos.role_template is None:
            continue
        new_parent_id, blocked = _find_chain_parent(
            db, before_order=pos.role_template.sort_order, lineage=lineage
        )
        if blocked:
            continue
        if new_parent_id is None:
            new_parent_id = _root_position_id(db)
        if new_parent_id != pos.parent_id:
            pos.parent_id = new_parent_id


def can_manage_via_role(db: Session, user_id: int, entity_type: str, entity_id: int) -> bool:
    """Does this user occupy any grants_management position for this entity?"""
    return db.scalar(
        select(Position.id)
        .join(RoleTemplate, Position.role_template_id == RoleTemplate.id)
        .join(PositionOccupant, PositionOccupant.position_id == Position.id)
        .where(
            Position.entity_type == entity_type,
            Position.entity_id == entity_id,
            RoleTemplate.grants_management.is_(True),
            PositionOccupant.user_id == user_id,
        )
        .limit(1)
    ) is not None


def set_position_occupants(db: Session, position: Position, user_ids: list[int]) -> None:
    """Replaces a position's occupant list wholesale — used by the generic
    roles-panel endpoint. The deletes are flushed *before* the inserts, not
    just before the final expire: SQLAlchemy's unit of work flushes inserts
    before deletes by default, so re-adding someone who's already an
    occupant (re-setting the same list, or swapping order) would otherwise
    collide with the (position_id, user_id) unique constraint on the row
    that hasn't been deleted yet."""
    for link in list(position.occupant_links):
        db.delete(link)
    db.flush()
    for uid in user_ids:
        db.add(PositionOccupant(position_id=position.id, user_id=uid))
    db.flush()
    db.expire(position, ["occupants", "occupant_links"])


def entity_roles(
    db: Session, event: str, entity_type: str, entity_id: int, names: dict[str, str]
) -> list[dict]:
    """The {template, position, occupants} rows applicable to one entity —
    what the frontend renders as that entity's "Roles" panel. A template
    added after the entity already existed shows up with no position yet
    (occupants empty, position_id None) rather than being hidden."""
    out = []
    for template in list_templates(db):
        if template.event != event:
            continue
        pos = get_role_position(db, template.id, entity_type, entity_id)
        out.append({
            "template_id": template.id,
            "title": pos.title if pos else _safe_title(template.title_template, names),
            "position_id": pos.id if pos else None,
            "occupants": list(pos.occupants) if pos else [],
        })
    return out
