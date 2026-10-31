from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select

from app.domains.access import service as access
from app.domains.audit.service import log as audit_log
from app.domains.auth.deps import DB, CurrentUser
from app.domains.events import lifecycle
from app.domains.events.models import (
    Event,
    EventCategory,
    EventStatus,
    EventTeam,
    EventTeamMember,
    EventKind,
    EventParticipation,
    tree_order,
)
from app.domains.events.role_sync import (
    lineage_for_event,
    lineage_for_membership,
    lineage_for_team,
)
from app.domains.events.schemas import (
    CategoryCreate,
    CategoryEdit,
    CategoryOut,
    EventCreate,
    EventDetailOut,
    EventEdit,
    EventOut,
    EventKindCreate,
    EventKindEdit,
    EventKindOut,
    MemberAdd,
    MemberOut,
    MemberRoleEdit,
    TeamCreate,
    TeamEdit,
    TeamOut,
)
from app.domains.events.service import (
    can_manage_event,
    can_manage_team,
    require_can_create,
    require_manage_event,
    require_manage_team,
    require_view,
    sub_team_ids,
)
from app.domains.inventory.models import InventoryAllocation
from app.domains.positions import role_engine
from app.domains.positions.schemas import EntityRoleOut
from app.domains.positions.service import resync_managers
from app.domains.users.models import User
from app.domains.users.schemas import UserBrief

router = APIRouter(prefix="/events", tags=["events"])


def _resolve_user(db: DB, user_id: int, what: str) -> int:
    if db.get(User, user_id) is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{what} not found")
    return user_id


def _default_kind(db: DB) -> EventKind | None:
    return db.scalar(select(EventKind).order_by(EventKind.sort_order))


def _resolve_kind(db: DB, kind_id: int | None) -> int:
    """Validate the kind, or fall back to the first one when none is given.
    An event must have a kind — if none exist yet, the org hasn't defined any
    event types, so creation is refused with a pointer to do that first."""
    if kind_id is not None:
        if db.get(EventKind, kind_id) is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown event kind")
        return kind_id
    default = _default_kind(db)
    if default is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "No event types exist yet — create one first (Events → Event types).",
        )
    return default.id


def _slugify(db: DB, name: str) -> str:
    base = "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-") or "kind"
    slug, n = base, 1
    while db.scalar(select(EventKind).where(EventKind.slug == slug)):
        n += 1
        slug = f"{base}-{n}"
    return slug


# --- event kinds (Event / Training / R&D / admin-defined) -----------
@router.get("/kinds")
def list_kinds(db: DB, user: CurrentUser) -> list[EventKindOut]:
    """The event kinds — one tab each under Events. Any viewer can read them."""
    access.require_privilege(db, user, "events.view")
    return [EventKindOut.model_validate(k) for k in db.scalars(select(EventKind).order_by(EventKind.sort_order))]


@router.post("/kinds", status_code=status.HTTP_201_CREATED)
def create_kind(payload: EventKindCreate, db: DB, user: CurrentUser) -> EventKindOut:
    access.require_privilege(db, user, "org.edit")
    next_order = (db.scalar(select(func.max(EventKind.sort_order))) or 0) + 1
    kind = EventKind(
        slug=_slugify(db, payload.name), name=payload.name,
        event_label=payload.event_label, category_label=payload.category_label,
        team_label=payload.team_label, member_label=payload.member_label,
        sort_order=next_order,
    )
    db.add(kind)
    db.commit()
    db.refresh(kind)
    return EventKindOut.model_validate(kind)


@router.patch("/kinds/{kind_id}")
def edit_kind(kind_id: int, payload: EventKindEdit, db: DB, user: CurrentUser) -> EventKindOut:
    access.require_privilege(db, user, "org.edit")
    kind = db.get(EventKind, kind_id)
    if kind is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Event kind not found")
    for field in ("name", "event_label", "category_label", "team_label", "member_label"):
        value = getattr(payload, field)
        if value is not None:
            setattr(kind, field, value)
    db.commit()
    db.refresh(kind)
    return EventKindOut.model_validate(kind)


@router.delete("/kinds/{kind_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_kind(kind_id: int, db: DB, user: CurrentUser) -> None:
    access.require_privilege(db, user, "org.edit")
    kind = db.get(EventKind, kind_id)
    if kind is None:
        return
    if db.scalar(select(func.count()).select_from(Event).where(Event.kind_id == kind_id)):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "This kind still has events — remove or reassign them first.",
        )
    from app.domains.positions.models import RoleTemplate
    if db.scalar(select(func.count()).select_from(RoleTemplate).where(RoleTemplate.event_kind_id == kind_id)):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "This kind still has automatic roles targeting it — remove them first.",
        )
    db.delete(kind)
    db.commit()


def _names(comp: Event, **extra: str) -> dict[str, str]:
    """Title-template placeholders. `{event}` is the generic name; `{competition}`
    is kept as an alias so templates written before the Events rename keep working."""
    return {"event": comp.name, "competition": comp.name, **extra}


def _entity_roles_out(
    db: DB, event: str, entity_type: str, entity_id: int, names: dict[str, str], kind_id: int | None
) -> list[EntityRoleOut]:
    return [
        EntityRoleOut(
            template_id=r["template_id"], title=r["title"], position_id=r["position_id"],
            occupants=[UserBrief.model_validate(u) for u in r["occupants"]],
        )
        for r in role_engine.entity_roles(db, event, entity_type, entity_id, names, kind_id)
    ]


def _kind_out(comp: Event) -> "EventKindOut | None":
    return EventKindOut.model_validate(comp.kind) if comp.kind else None


def _team_out(db: DB, comp: Event, team: EventTeam, can_manage: bool, user: User) -> TeamOut:
    names = _names(comp, team=team.name)
    return TeamOut(
        id=team.id,
        name=team.name,
        parent_team_id=team.parent_team_id,
        award=team.award,
        roles=_entity_roles_out(db, "team_created", "team", team.id, names, comp.kind_id),
        members=[
            MemberOut(id=m.id, user=UserBrief.model_validate(m.user), role=m.role)
            for m in team.members
        ],
        can_manage_members=can_manage or can_manage_team(db, user, team),
        can_edit=can_manage or _can_edit_team(db, user, team),
    )


def _can_edit_team(db: DB, user: User, team: EventTeam) -> bool:
    """A top-level team's record belongs to its event's managers; a sub-team's
    also to whoever manages the team it sits in."""
    if team.parent is not None and can_manage_team(db, user, team.parent):
        return True
    return can_manage_event(db, user, team.category.event_id)


def _require_edit_team(db: DB, user: User, team: EventTeam) -> None:
    if not _can_edit_team(db, user, team):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "You must manage this team's event (or its parent team)."
        )


def _parent_for(db: DB, team_id: int, category_id: int) -> EventTeam:
    parent = _get_team(db, team_id)
    if parent.category_id != category_id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "A sub-team must be in the same category as its parent."
        )
    return parent


def _active_teams(cat: EventCategory) -> list[EventTeam]:
    return [t for t in tree_order(cat.teams) if t.deleted_at is None]


def _counts(comp: Event) -> tuple[int, int]:
    cats = len(comp.categories)
    active = [_active_teams(c) for c in comp.categories]
    teams = sum(len(ts) for ts in active)
    return cats, teams


def _member_count(db: DB, comp: Event) -> int:
    """Distinct people involved in the event: everyone occupying an event- or
    team-level role (however they were added — mirrored from another system,
    automatic roles, etc.) plus anyone on a team's explicit roster."""
    ids: set[int] = set()
    for r in role_engine.entity_roles(
        db, "event_created", "event", comp.id, _names(comp), comp.kind_id
    ):
        ids.update(u.id for u in r["occupants"])
    for cat in comp.categories:
        for t in _active_teams(cat):
            ids.update(m.user_id for m in t.members)
            for r in role_engine.entity_roles(
                db, "team_created", "team", t.id, _names(comp, team=t.name), comp.kind_id
            ):
                ids.update(u.id for u in r["occupants"])
    return len(ids)


def _base_out(db: DB, comp: Event, manage: bool) -> dict:
    cats, teams = _counts(comp)
    members = _member_count(db, comp)
    alloc = db.scalar(
        select(func.count()).select_from(InventoryAllocation).where(
            InventoryAllocation.event_id == comp.id
        )
    ) or 0
    return dict(
        id=comp.id, name=comp.name, full_name=comp.full_name, status=comp.status,
        description=comp.description,
        start_date=comp.start_date, end_date=comp.end_date, created_at=comp.created_at,
        awards=comp.awards,
        applications_open=comp.applications_open,
        public_summary=comp.public_summary,
        kind=_kind_out(comp),
        roles=_entity_roles_out(db, "event_created", "event", comp.id, _names(comp), comp.kind_id),
        category_count=cats, team_count=teams, member_count=members, allocation_count=alloc,
        can_manage=manage,
        code=comp.code,
        record={k: getattr(comp, k) for k in RECORD_FIELDS if getattr(comp, k) not in (None, "")},
        participation_count=db.scalar(
            select(func.count()).select_from(EventParticipation).where(EventParticipation.event_id == comp.id)
        ) or 0,
    )


# The event-record columns surfaced on the event card, in display order.
RECORD_FIELDS = [
    "level", "organizer", "location", "tracks", "result", "registered_count",
    "participants_count", "teams_count", "mentors", "captains", "contact",
    "budget_total", "actual_spend", "currency", "funding_source", "prep_date",
    "competition_days", "registration_form", "roster_source", "notes",
]


@router.get("/{event_id}/participations")
def event_participations(event_id: int, db: DB, user: CurrentUser) -> list[dict]:
    """Everyone the member database records as taking part in this event."""
    access.require_privilege(db, user, "members.view")
    rows = db.scalars(select(EventParticipation).where(EventParticipation.event_id == event_id))
    out = [
        {
            "id": p.id, "member_id": p.member_id, "mtr_id": p.member.mtr_id, "name": p.member.full_name,
            "role": p.role, "team": p.team, "mentor": p.mentor, "rating": p.rating,
            "registered_at": p.registered_at,
        }
        for p in rows
    ]
    return sorted(out, key=lambda r: (r["team"] or "~", r["name"].lower()))


def _list_out(db: DB, user: User, comp: Event) -> EventOut:
    return EventOut(**_base_out(db, comp, can_manage_event(db, user, comp.id)))


def _detail_out(db: DB, user: User, comp: Event) -> EventDetailOut:
    manage = can_manage_event(db, user, comp.id)
    categories = [
        CategoryOut(
            id=cat.id,
            name=cat.name,
            teams=[_team_out(db, comp, t, manage, user) for t in _active_teams(cat)],
        )
        for cat in comp.categories
    ]
    return EventDetailOut(**_base_out(db, comp, manage), categories=categories)


def _get_comp(db: DB, event_id: int) -> Event:
    comp = db.get(Event, event_id)
    if comp is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Event not found")
    return comp


def _get_team(db: DB, team_id: int) -> EventTeam:
    team = db.get(EventTeam, team_id)
    if team is None or team.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Team not found")
    return team


def _team_event(team: EventTeam) -> Event:
    return team.category.event


# --- teams & categories (literal routes, before /{event_id}) --------
@router.delete("/categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_category(category_id: int, db: DB, user: CurrentUser) -> None:
    cat = db.get(EventCategory, category_id)
    if cat is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Category not found")
    require_manage_event(db, user, cat.event_id)
    if _active_teams(cat):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "This category still has teams — remove them first.",
        )
    db.delete(cat)
    db.commit()


@router.patch("/categories/{category_id}")
def edit_category(category_id: int, payload: CategoryEdit, db: DB, user: CurrentUser) -> CategoryOut:
    cat = db.get(EventCategory, category_id)
    if cat is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Category not found")
    require_manage_event(db, user, cat.event_id)
    if payload.name is not None:
        cat.name = payload.name
    db.commit()
    db.refresh(cat)
    comp = cat.event
    return CategoryOut(
        id=cat.id, name=cat.name,
        teams=[_team_out(db, comp, t, True, user) for t in _active_teams(cat)],
    )


@router.post("/categories/{category_id}/teams", status_code=status.HTTP_201_CREATED)
def add_team(category_id: int, payload: TeamCreate, db: DB, user: CurrentUser) -> TeamOut:
    cat = db.get(EventCategory, category_id)
    if cat is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Category not found")
    parent = None
    if payload.parent_team_id is not None:
        parent = _parent_for(db, payload.parent_team_id, category_id)
        require_manage_team(db, user, parent)  # a team's managers may carve sub-teams
    else:
        require_manage_event(db, user, cat.event_id)
    comp = cat.event
    team = EventTeam(name=payload.name, parent_team_id=parent.id if parent else None)
    cat.teams.append(team)  # keeps an already-loaded category's team list current
    db.flush()
    role_engine.apply_event(
        db, event="team_created", entity_type="team", entity_id=team.id,
        lineage=lineage_for_team(comp, team.id), names=_names(comp, team=team.name),
        kind_id=comp.kind_id, root_position_id=payload.role_root_position_id,
        nest_in_id=team.parent_team_id,
    )
    if parent is not None:
        audit_log(db, user.id, "events", "sub_team_added", "event_team", team.id,
                  {"team": team.name, "parent_team_id": parent.id})
    resync_managers(db)
    db.commit()
    db.refresh(team)
    return _team_out(db, comp, team, can_manage_event(db, user, comp.id), user)


@router.patch("/teams/{team_id}")
def edit_team(team_id: int, payload: TeamEdit, db: DB, user: CurrentUser) -> TeamOut:
    team = _get_team(db, team_id)
    comp = _team_event(team)
    _require_edit_team(db, user, team)
    if payload.clear_parent or payload.parent_team_id is not None:
        _move_team(db, user, comp, team, None if payload.clear_parent else payload.parent_team_id)
    if payload.name is not None and payload.name != team.name:
        team.name = payload.name
        names = _names(comp, team=team.name)
        role_engine.retitle_positions_for_entity(db, "team", team.id, names)
        for member in team.members:
            role_engine.retitle_positions_for_entity(
                db, "membership", member.id, {**names, "member": member.user.full_name}
            )
    if payload.clear_award:
        team.award = None
    elif payload.award is not None:
        team.award = payload.award
    resync_managers(db)
    db.commit()
    db.refresh(team)
    return _team_out(db, comp, team, can_manage_event(db, user, comp.id), user)


def _move_team(db: DB, user: User, comp: Event, team: EventTeam, parent_id: int | None) -> None:
    """Re-nest a team (with its own sub-teams) under another team of its
    category, or back to the top level. Moving changes which tree the team
    belongs to, so it's the event managers' call."""
    if parent_id == team.parent_team_id:
        return
    require_manage_event(db, user, comp.id)
    if parent_id is not None:
        if parent_id == team.id or parent_id in sub_team_ids(db, team.id):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "A team can't be nested inside itself or its own sub-teams."
            )
        _parent_for(db, parent_id, team.category_id)
    team.parent_team_id = parent_id
    db.flush()
    db.expire(team, ["parent"])
    role_engine.resync_position_parent(
        db, entity_type="team", entity_id=team.id,
        lineage=lineage_for_team(comp, team.id), kind_id=comp.kind_id, nest_in_id=parent_id,
    )
    audit_log(db, user.id, "events", "team_moved", "event_team", team.id,
              {"team": team.name, "parent_team_id": parent_id})


@router.delete("/teams/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_team(team_id: int, db: DB, user: CurrentUser, permanent: bool = False) -> None:
    """Soft-deletes by default — a team is historical context (who competed,
    allocations, task history). `permanent=true` really removes it, admin
    only. Either way its role positions (and its members' role positions)
    are removed from the org chart — the chart only shows active work, the
    team row itself is what stays queryable on a soft delete."""
    team = _get_team(db, team_id)
    _require_edit_team(db, user, team)
    if sub_team_ids(db, team.id):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "This team still has sub-teams — remove or move them first.",
        )
    member_ids = [m.id for m in team.members]
    if permanent:
        if not access.is_top(db, user):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "Only a top-level user can permanently delete a team"
            )
        audit_log(db, user.id, "events", "team_purged", "event_team", team.id,
                  {"team": team.name})
    else:
        audit_log(db, user.id, "events", "team_deleted", "event_team", team.id,
                  {"team": team.name})
        team.deleted_at = datetime.now(timezone.utc)
    for mid in member_ids:
        role_engine.delete_positions_for_entity(db, "membership", mid)
    role_engine.delete_positions_for_entity(db, "team", team.id)
    if permanent:
        db.delete(team)
    resync_managers(db)
    db.commit()


@router.post("/teams/{team_id}/members", status_code=status.HTTP_201_CREATED)
def add_member(team_id: int, payload: MemberAdd, db: DB, user: CurrentUser) -> TeamOut:
    team = _get_team(db, team_id)
    comp = _team_event(team)
    require_manage_team(db, user, team)  # a scoped team manager qualifies here
    _resolve_user(db, payload.user_id, "Member")
    exists = db.scalar(
        select(EventTeamMember).where(
            EventTeamMember.team_id == team_id,
            EventTeamMember.user_id == payload.user_id,
        )
    )
    if exists is None:
        member = EventTeamMember(team_id=team_id, user_id=payload.user_id)
        db.add(member)
        db.flush()
        member_user = db.get(User, payload.user_id)
        role_engine.apply_event(
            db, event="team_member_added", entity_type="membership", entity_id=member.id,
            lineage=lineage_for_membership(comp, team.id, member.id),
            names=_names(comp, team=team.name, member=member_user.full_name),
            kind_id=comp.kind_id,
            member_id=payload.user_id, root_position_id=payload.role_root_position_id,
        )
        resync_managers(db)
        audit_log(db, user.id, "events", "member_added", "event_team", team.id,
                  {"team": team.name, "user_id": payload.user_id})
        db.commit()
        db.refresh(team)
    return _team_out(db, comp, team, can_manage_team(db, user, team), user)


@router.delete("/teams/{team_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(team_id: int, user_id: int, db: DB, user: CurrentUser) -> None:
    team = _get_team(db, team_id)
    require_manage_team(db, user, team)
    member = db.scalar(
        select(EventTeamMember).where(
            EventTeamMember.team_id == team_id,
            EventTeamMember.user_id == user_id,
        )
    )
    if member is not None:
        role_engine.delete_positions_for_entity(db, "membership", member.id)
        db.delete(member)
        resync_managers(db)
        audit_log(db, user.id, "events", "member_removed", "event_team", team.id,
                  {"team": team.name, "user_id": user_id})
        db.commit()


@router.patch("/teams/{team_id}/members/{user_id}")
def edit_member_role(
    team_id: int, user_id: int, payload: MemberRoleEdit, db: DB, user: CurrentUser
) -> TeamOut:
    """Set a member's competition role — the free-form credit shown in the public
    Hall of Fame (e.g. "Electrical", "CEO", "Pilot · CTO"). Purely descriptive:
    it does not touch the org role/position engine."""
    team = _get_team(db, team_id)
    comp = _team_event(team)
    require_manage_team(db, user, team)
    member = db.scalar(
        select(EventTeamMember).where(
            EventTeamMember.team_id == team_id,
            EventTeamMember.user_id == user_id,
        )
    )
    if member is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Member not found on this team")
    if payload.clear_role:
        member.role = None
    elif payload.role is not None:
        member.role = payload.role
    db.commit()
    db.refresh(team)
    return _team_out(db, comp, team, can_manage_team(db, user, team), user)


# --- events ---------------------------------------------------------
@router.get("")
def list_events(
    db: DB, user: CurrentUser, include_archived: bool = False, kind_id: int | None = None
) -> list[EventOut]:
    require_view(db, user)
    query = select(Event)
    if kind_id is not None:
        query = query.where(Event.kind_id == kind_id)
    if not include_archived:
        query = query.where(Event.status == EventStatus.ACTIVE)
    comps = db.scalars(query.order_by(Event.name)).all()
    return [_list_out(db, user, c) for c in comps]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_event(payload: EventCreate, db: DB, user: CurrentUser) -> EventDetailOut:
    require_can_create(db, user)
    if db.scalar(select(Event).where(Event.name == payload.name)):
        raise HTTPException(status.HTTP_409_CONFLICT, "An event with that name already exists")
    kind_id = _resolve_kind(db, payload.kind_id)
    comp = Event(
        name=payload.name,
        full_name=payload.full_name,
        kind_id=kind_id,
        description=payload.description,
        start_date=payload.start_date,
        end_date=payload.end_date,
        applications_open=payload.applications_open,
        public_summary=(payload.public_summary or "").strip() or None,
    )
    db.add(comp)
    db.flush()
    role_engine.apply_event(
        db, event="event_created", entity_type="event", entity_id=comp.id,
        lineage=lineage_for_event(comp), names=_names(comp), kind_id=comp.kind_id,
        root_position_id=payload.role_root_position_id,
    )
    resync_managers(db)
    db.commit()
    db.refresh(comp)
    return _detail_out(db, user, comp)


@router.get("/{event_id}")
def get_event(event_id: int, db: DB, user: CurrentUser) -> EventDetailOut:
    require_view(db, user)
    return _detail_out(db, user, _get_comp(db, event_id))


@router.patch("/{event_id}")
def edit_event(
    event_id: int, payload: EventEdit, db: DB, user: CurrentUser
) -> EventOut:
    require_manage_event(db, user, event_id)
    comp = _get_comp(db, event_id)
    if payload.name is not None and payload.name != comp.name:
        if db.scalar(select(Event).where(Event.name == payload.name)):
            raise HTTPException(status.HTTP_409_CONFLICT, "A event with that name already exists")
        comp.name = payload.name
        role_engine.retitle_positions_for_entity(db, "event", comp.id, _names(comp))
        for cat in comp.categories:
            for team in cat.teams:
                names = _names(comp, team=team.name)
                role_engine.retitle_positions_for_entity(db, "team", team.id, names)
                for member in team.members:
                    role_engine.retitle_positions_for_entity(
                        db, "membership", member.id, {**names, "member": member.user.full_name}
                    )
    if payload.clear_full_name:
        comp.full_name = None
    elif payload.full_name is not None:
        comp.full_name = payload.full_name
    if payload.description is not None:
        comp.description = payload.description
    if payload.applications_open is not None:
        comp.applications_open = payload.applications_open
    if payload.public_summary is not None:
        comp.public_summary = payload.public_summary.strip() or None
    if payload.clear_awards:
        comp.awards = None
    elif payload.awards is not None:
        comp.awards = payload.awards
    status_changed = payload.status is not None and payload.status != comp.status
    comp.start_date = None if payload.clear_start_date else (payload.start_date or comp.start_date)
    comp.end_date = None if payload.clear_end_date else (payload.end_date or comp.end_date)
    if status_changed and payload.status == EventStatus.ARCHIVED:
        # the seats leave the org chart — the org chart only shows active
        # work — but who sat in them is kept on the event's record
        lifecycle.archive_event(db, comp)
    elif status_changed and payload.status == EventStatus.ACTIVE:
        lifecycle.reactivate_event(db, comp)
    db.commit()
    db.refresh(comp)
    return _list_out(db, user, comp)


@router.delete("/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_event(event_id: int, db: DB, user: CurrentUser) -> None:
    require_manage_event(db, user, event_id)
    comp = _get_comp(db, event_id)
    in_use = db.scalar(
        select(func.count()).select_from(InventoryAllocation).where(
            InventoryAllocation.event_id == event_id
        )
    )
    if in_use:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"{in_use} allocation(s) reference this event — archive it instead.",
        )
    lifecycle.remove_event_seats(db, comp)
    db.delete(comp)
    resync_managers(db)
    db.commit()


# --- categories (nested under a event) ------------------------------
@router.post("/{event_id}/categories", status_code=status.HTTP_201_CREATED)
def add_category(event_id: int, payload: CategoryCreate, db: DB, user: CurrentUser) -> CategoryOut:
    require_manage_event(db, user, event_id)
    _get_comp(db, event_id)
    cat = EventCategory(event_id=event_id, name=payload.name)
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return CategoryOut(id=cat.id, name=cat.name, teams=[])
