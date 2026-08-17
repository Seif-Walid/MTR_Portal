from collections import defaultdict
from datetime import date

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select

from app.domains.access import service as access
from app.domains.auth.deps import DB, CurrentUser
from app.domains.events.models import Event, EventCategory, EventStatus, EventTeam
from app.domains.events.service import (
    can_manage_team,
    team_member_user_ids,
    user_event_team_ids,
)
from app.domains.hierarchy.service import subtree_ids
from app.domains.positions.models import Position, PositionOccupant
from app.domains.tasks.models import Task
from app.domains.timeblocks import service as timeblocks
from app.domains.users.models import User
from app.domains.users.schemas import UserBrief

router = APIRouter(prefix="/team", tags=["team"])


class TreeNode(BaseModel):
    id: int
    full_name: str
    email: str
    department: str | None
    level: str | None  # effective access level name — the org's reflection
    manager_id: int | None
    is_active: bool
    can_manage: bool  # may the current user add/edit under this node
    children: list["TreeNode"] = []


TreeNode.model_rebuild()


@router.get("/tree")
def org_tree(db: DB, user: CurrentUser) -> list[TreeNode]:
    """Nested org chart. users.manage sees (and manages) the whole
    organization; everyone else sees the subtree rooted at themselves,
    view-only."""
    access.require_privilege(db, user, "people.view")
    if access.has_privilege(db, user, "users.manage"):
        users = db.scalars(select(User).order_by(User.full_name)).all()
        manageable: set[int] = {u.id for u in users}
    else:
        scope = subtree_ids(db, user.id, include_self=True)
        users = db.scalars(
            select(User).where(User.id.in_(scope)).order_by(User.full_name)
        ).all()
        manageable = set()

    present = {u.id for u in users}
    children_map: dict[int | None, list[User]] = defaultdict(list)
    for u in users:
        children_map[u.manager_id].append(u)

    levels = access.effective_levels_bulk(db, [u.id for u in users])

    def build(u: User) -> TreeNode:
        lvl = levels.get(u.id)
        return TreeNode(
            id=u.id,
            full_name=u.full_name,
            email=u.email,
            department=u.department,
            level=lvl.name if lvl else None,
            manager_id=u.manager_id,
            is_active=u.is_active,
            can_manage=u.id in manageable,
            children=[build(c) for c in children_map.get(u.id, [])],
        )

    if access.has_privilege(db, user, "users.manage"):
        roots = [u for u in users if u.manager_id is None or u.manager_id not in present]
    else:
        roots = [u for u in users if u.id == user.id]
    return [build(r) for r in roots]


class TeamMemberOut(BaseModel):
    user: UserBrief
    manager_id: int | None
    is_direct_report: bool
    task_counts: dict[str, int]
    total_tasks: int


@router.get("")
def my_team(db: DB, user: CurrentUser) -> list[TeamMemberOut]:
    """Everyone in the current user's subtree with per-status task counts."""
    access.require_privilege(db, user, "people.view")
    ids = subtree_ids(db, user.id)
    if not ids:
        return []
    members = db.scalars(
        select(User).where(User.id.in_(ids)).order_by(User.full_name)
    ).all()
    counts = db.execute(
        select(Task.assignee_id, Task.status, func.count())
        .where(Task.assignee_id.in_(ids))
        .group_by(Task.assignee_id, Task.status)
    ).all()
    by_user: dict[int, dict[str, int]] = {}
    for assignee_id, task_status, count in counts:
        by_user.setdefault(assignee_id, {})[task_status] = count

    return [
        TeamMemberOut(
            user=UserBrief.model_validate(m),
            manager_id=m.manager_id,
            is_direct_report=m.manager_id == user.id,
            task_counts=by_user.get(m.id, {}),
            total_tasks=sum(by_user.get(m.id, {}).values()),
        )
        for m in members
    ]


class TeamBlockOut(BaseModel):
    kind: str  # "org" | "event"
    team_id: int | None  # event-team id; null for the org block
    name: str
    event_name: str | None = None
    event_id: int | None = None
    members: list[TeamMemberOut]
    # calendar time-block scheduling: which org unit this block anchors to (org
    # kind only) and whether the viewer may create/edit its time blocks.
    position_id: int | None = None
    can_schedule: bool = False
    # event span (event kind only) — time blocks can't fall outside it
    event_start: date | None = None
    event_end: date | None = None


def _task_counts_for(db, member_ids: set[int], team_id: int | None) -> dict[int, dict[str, int]]:
    """Per-member per-status task counts. Scoped to one event team when team_id
    is given (its own board), else every task assigned to the member."""
    if not member_ids:
        return {}
    query = (
        select(Task.assignee_id, Task.status, func.count())
        .where(Task.assignee_id.in_(member_ids))
        .group_by(Task.assignee_id, Task.status)
    )
    if team_id is not None:
        query = query.where(Task.event_team_id == team_id)
    by_user: dict[int, dict[str, int]] = {}
    for assignee_id, task_status, count in db.execute(query).all():
        by_user.setdefault(assignee_id, {})[task_status] = count
    return by_user


def _members_out(members, counts, manager_ref_id: int | None) -> list[TeamMemberOut]:
    return [
        TeamMemberOut(
            user=UserBrief.model_validate(m),
            manager_id=m.manager_id,
            is_direct_report=m.manager_id == manager_ref_id,
            task_counts=counts.get(m.id, {}),
            total_tasks=sum(counts.get(m.id, {}).values()),
        )
        for m in members
    ]


def _org_team_ids(db, user_id: int) -> set[int]:
    """Everyone on the user's *permanent* org team, from two sources so it works
    however the org is modelled:

    - `manager_id` subtree (used when the hierarchy is populated), and
    - the real Position tree (used here): the people occupying seats beneath a
      real position the user occupies. If the user only occupies leaf seats
      (they're a member, not a lead), their team is the unit under their seat's
      parent — i.e. their peers.

    Role-template ("hat") positions are ignored — they're the *event* teams,
    surfaced separately."""
    ids = set(subtree_ids(db, user_id))

    # real positions the user occupies
    my_real = db.scalars(
        select(Position.id)
        .join(PositionOccupant, PositionOccupant.position_id == Position.id)
        .where(PositionOccupant.user_id == user_id, Position.role_template_id.is_(None))
    ).all()
    if not my_real:
        return ids

    # real org tree in memory (small): parent -> children, position -> occupants
    real = db.scalars(select(Position).where(Position.role_template_id.is_(None))).all()
    children: dict[int, list[int]] = defaultdict(list)
    parent_of: dict[int, int | None] = {}
    occ_of: dict[int, list[int]] = {}
    for p in real:
        parent_of[p.id] = p.parent_id
        children[p.parent_id].append(p.id)
        occ_of[p.id] = [l.user_id for l in p.occupant_links]

    def descendants(pos_id: int) -> list[int]:
        out, stack = [], list(children.get(pos_id, []))
        while stack:
            cur = stack.pop()
            out.append(cur)
            stack.extend(children.get(cur, []))
        return out

    for pid in my_real:
        below = [u for d in descendants(pid) for u in occ_of.get(d, [])]
        if not children.get(pid) and parent_of.get(pid) is not None:
            # a leaf seat (a member): show the unit under their parent
            below = [u for d in descendants(parent_of[pid]) for u in occ_of.get(d, [])]
        ids.update(below)
    ids.discard(user_id)
    return ids


@router.get("/mine")
def my_teams(db: DB, user: CurrentUser) -> list[TeamBlockOut]:
    """Every team the user belongs to as its own block: the permanent org team
    first (derived from the org hierarchy / Position tree), then each active
    event team they hold a seat on, with task counts scoped to that team."""
    access.require_privilege(db, user, "people.view")
    blocks: list[TeamBlockOut] = []

    # Org block — the permanent org team. Always rendered with the viewer in
    # it, even when they have no reports/peers (a team of one is still a team).
    org_ids = _org_team_ids(db, user.id) | {user.id}
    org_members = db.scalars(
        select(User).where(User.id.in_(org_ids)).order_by(User.full_name)
    ).all()
    org_position_id, org_can_schedule = timeblocks.org_root_position(db, user)
    blocks.append(
        TeamBlockOut(
            kind="org",
            team_id=None,
            name="My Team",
            members=_members_out(org_members, _task_counts_for(db, org_ids, None), user.id),
            position_id=org_position_id,
            can_schedule=org_can_schedule,
        )
    )

    # Event blocks — active teams (not soft-deleted) on active events.
    for team_id in user_event_team_ids(db, user.id):
        team = db.get(EventTeam, team_id)
        if team is None or team.deleted_at is not None:
            continue
        cat = db.get(EventCategory, team.category_id)
        event = db.get(Event, cat.event_id) if cat else None
        if event is None or event.status != EventStatus.ACTIVE:
            continue
        member_ids = team_member_user_ids(db, team_id)
        if not member_ids:
            continue
        team_members = db.scalars(
            select(User).where(User.id.in_(member_ids)).order_by(User.full_name)
        ).all()
        blocks.append(
            TeamBlockOut(
                kind="event",
                team_id=team.id,
                name=team.name,
                event_name=event.name,
                event_id=event.id,
                members=_members_out(
                    team_members, _task_counts_for(db, member_ids, team.id), user.id
                ),
                can_schedule=can_manage_team(db, user, team),
                event_start=event.start_date,
                event_end=event.end_date,
            )
        )

    # stable order: org first, then event teams by name
    blocks.sort(key=lambda b: (b.kind != "org", b.event_name or "", b.name))
    return blocks


@router.get("/{member_id}/check")
def check_member(member_id: int, db: DB, user: CurrentUser) -> dict[str, bool]:
    """Whether member_id is inside the current user's subtree (used by the UI
    before drilling down; the tasks endpoint enforces this anyway)."""
    if member_id == user.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "That's you")
    return {"in_subtree": member_id in subtree_ids(db, user.id)}
