from collections import defaultdict

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.domains.audit.service import log as audit_log
from app.domains.auth.deps import DB, CurrentUser
from app.domains.competitions.role_sync import resync_all as resync_all_role_positions
from app.domains.competitions.service import can_manage_entity
from app.domains.hierarchy.service import is_org_manager
from app.domains.positions import role_engine
from app.domains.positions.models import OrgAuditLog, Position
from app.domains.positions.schemas import (
    EntityRoleOut,
    OccupantsSet,
    PositionCreate,
    PositionEdit,
    PositionNode,
    RoleRootOut,
    RoleTemplateCreate,
    RoleTemplateEdit,
    RoleTemplateOut,
)
from app.domains.positions.service import (
    assert_no_cycle,
    audit,
    clear_user_from_other_positions,
    resync_managers,
)
from app.domains.users.models import User
from app.domains.users.schemas import UserBrief

router = APIRouter(prefix="/org", tags=["organization"])


def _require_org_manager(user: User) -> None:
    if not is_org_manager(user):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Only the CEO or an admin can edit the org tree"
        )


def _resolve_occupants(db: DB, user_ids: list[int]) -> list[int]:
    for uid in user_ids:
        if db.get(User, uid) is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Occupant not found")
    return user_ids


def _set_real_occupants(db: DB, position: Position, user_ids: list[int]) -> None:
    role_engine.set_position_occupants(db, position, user_ids)
    for uid in user_ids:
        clear_user_from_other_positions(db, uid, keep_position_id=position.id)


@router.get("/tree")
def org_tree(db: DB, user: CurrentUser) -> list[PositionNode]:
    """The whole position tree. Vacant seats included. Any signed-in user may view."""
    positions = list(db.scalars(select(Position)))
    children: dict[int | None, list[Position]] = defaultdict(list)
    for p in positions:
        children[p.parent_id].append(p)
    for group in children.values():
        group.sort(key=lambda p: p.title.lower())

    def build(p: Position) -> PositionNode:
        node = PositionNode.model_validate(p)
        node.children = [build(c) for c in children.get(p.id, [])]
        return node

    return [build(p) for p in children.get(None, [])]


@router.post("/positions", status_code=status.HTTP_201_CREATED)
def create_position(payload: PositionCreate, db: DB, user: CurrentUser) -> PositionNode:
    _require_org_manager(user)
    if payload.parent_id is None:
        if db.scalar(select(Position).where(Position.parent_id.is_(None))) is not None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "The org already has a root — add this under an existing position.",
            )
    elif db.get(Position, payload.parent_id) is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Parent position not found")

    occupant_ids = _resolve_occupants(db, payload.occupant_ids)
    position = Position(
        title=payload.title,
        parent_id=payload.parent_id,
        is_technical=payload.is_technical,
    )
    db.add(position)
    db.flush()
    _set_real_occupants(db, position, occupant_ids)
    resync_managers(db)
    audit(db, user.id, "create", position.id,
          {"title": position.title, "parent_id": position.parent_id, "occupant_ids": occupant_ids})
    db.commit()
    db.refresh(position)
    return PositionNode.model_validate(position)


@router.patch("/positions/{position_id}")
def edit_position(position_id: int, payload: PositionEdit, db: DB, user: CurrentUser) -> PositionNode:
    _require_org_manager(user)
    position = db.get(Position, position_id)
    if position is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Position not found")

    if payload.title is not None:
        position.title = payload.title
    if payload.is_technical is not None:
        position.is_technical = payload.is_technical
    if payload.parent_id is not None and payload.parent_id != position.parent_id:
        if db.get(Position, payload.parent_id) is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Parent position not found")
        assert_no_cycle(db, position.id, payload.parent_id)
        position.parent_id = payload.parent_id
    if payload.occupant_ids is not None:
        occupant_ids = _resolve_occupants(db, payload.occupant_ids)
        _set_real_occupants(db, position, occupant_ids)

    db.flush()
    resync_managers(db)
    audit(db, user.id, "edit", position.id,
          {"title": position.title, "parent_id": position.parent_id,
           "occupant_ids": [u.id for u in position.occupants]})
    db.commit()
    db.refresh(position)
    return PositionNode.model_validate(position)


@router.delete("/positions/{position_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_position(position_id: int, db: DB, user: CurrentUser) -> None:
    _require_org_manager(user)
    position = db.get(Position, position_id)
    if position is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Position not found")
    if db.scalar(select(Position).where(Position.parent_id == position_id)) is not None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Reparent or remove the positions under this one first.",
        )
    # former occupants are now unplaced
    for uid in [u.id for u in position.occupants]:
        occ = db.get(User, uid)
        if occ is not None:
            occ.manager_id = None
    audit(db, user.id, "delete", position_id, {"title": position.title})
    db.delete(position)
    db.flush()
    resync_managers(db)
    db.commit()


@router.get("/audit")
def org_audit(db: DB, user: CurrentUser, limit: int = 50) -> list[dict]:
    _require_org_manager(user)
    rows = db.scalars(
        select(OrgAuditLog).order_by(OrgAuditLog.created_at.desc()).limit(min(limit, 200))
    )
    out = []
    for r in rows:
        actor = db.get(User, r.actor_id) if r.actor_id else None
        out.append({
            "id": r.id,
            "actor": actor.full_name if actor else "—",
            "action": r.action,
            "position_id": r.position_id,
            "detail": r.detail,
            "created_at": r.created_at.isoformat(),
        })
    return out


# --- role templates (admin-configurable auto-seating) ----------------------
def _template_out(template: role_engine.RoleTemplate, all_templates: list[role_engine.RoleTemplate]) -> RoleTemplateOut:
    out = RoleTemplateOut.model_validate(template)
    out.parent_template_id = role_engine.template_chain_parent_id(all_templates, template)
    return out


@router.get("/roles/templates")
def list_role_templates(db: DB, user: CurrentUser) -> list[RoleTemplateOut]:
    templates = role_engine.list_templates(db)
    return [_template_out(t, templates) for t in templates]


@router.post("/roles/templates", status_code=status.HTTP_201_CREATED)
def create_role_template(payload: RoleTemplateCreate, db: DB, user: CurrentUser) -> RoleTemplateOut:
    _require_org_manager(user)
    template = role_engine.create_template(
        db, title_template=payload.title_template, event=payload.event,
        grants_management=payload.grants_management, auto_assign_creator=payload.auto_assign_creator,
        insert_after_id=payload.insert_after_id,
    )
    db.commit()
    db.refresh(template)
    return _template_out(template, role_engine.list_templates(db))


@router.patch("/roles/templates/{template_id}")
def edit_role_template(
    template_id: int, payload: RoleTemplateEdit, db: DB, user: CurrentUser
) -> RoleTemplateOut:
    _require_org_manager(user)
    template = role_engine.update_template(
        db, template_id, title_template=payload.title_template,
        grants_management=payload.grants_management, auto_assign_creator=payload.auto_assign_creator,
        new_sort_order=payload.sort_order,
    )
    if payload.sort_order is not None:
        resync_all_role_positions(db)
        resync_managers(db)
    db.commit()
    db.refresh(template)
    return _template_out(template, role_engine.list_templates(db))


@router.delete("/roles/templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_role_template(template_id: int, db: DB, user: CurrentUser) -> None:
    _require_org_manager(user)
    role_engine.delete_template(db, template_id)
    resync_all_role_positions(db)
    resync_managers(db)
    db.commit()


@router.get("/roles/root")
def role_root(db: DB, user: CurrentUser) -> RoleRootOut:
    return RoleRootOut(
        root_position_id=role_engine.root_position_id(db),
        has_templates=role_engine.has_templates(db),
    )


@router.put("/roles/positions/{position_id}/occupants")
def set_role_position_occupants(
    position_id: int, payload: OccupantsSet, db: DB, user: CurrentUser
) -> EntityRoleOut:
    """Assign who fills a role-template position. Anyone who manages the
    linked competition/team (per competitions.service.can_manage_entity) may
    do this, not just CEO/Admin — matching how appointing a PM/lead used to
    be reachable by the competition's own managers, not just org-tree
    editors."""
    position = db.get(Position, position_id)
    if position is None or position.role_template_id is None or position.entity_type is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Role position not found")
    if not is_org_manager(user) and not can_manage_entity(
        db, user, position.entity_type, position.entity_id
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You don't manage this competition/team")
    occupant_ids = _resolve_occupants(db, payload.user_ids)
    role_engine.set_position_occupants(db, position, occupant_ids)
    resync_managers(db)
    audit_log(db, user.id, "positions", "role_occupants_changed", position.entity_type, position.entity_id,
              {"role": position.title, "occupant_ids": occupant_ids})
    db.commit()
    db.refresh(position)
    return EntityRoleOut(
        template_id=position.role_template_id, title=position.title,
        position_id=position.id, occupants=[UserBrief.model_validate(u) for u in position.occupants],
    )
