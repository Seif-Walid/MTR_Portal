"""Org-hierarchy traversal and the permission predicates built on it.

The hierarchy is data-driven: users.manager_id forms a tree. Every permission
below derives from that tree at query time, so moving a person in the tree
instantly changes who can see and task them. What a person may *do at all*
comes from the access ladder (app/domains/access); this module only answers
the structural questions — who sits below/above whom — plus the predicates
that combine both.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domains.access import service as access
from app.domains.positions.models import Position, PositionOccupant
from app.domains.users.models import User


def subtree_ids(db: Session, root_id: int, include_self: bool = False) -> set[int]:
    """IDs of everyone strictly below root_id, via a recursive CTE."""
    base = select(User.id).where(User.manager_id == root_id)
    tree = base.cte(name="subtree", recursive=True)
    tree = tree.union_all(select(User.id).where(User.manager_id == tree.c.id))
    ids = set(db.scalars(select(tree.c.id)))
    if include_self:
        ids.add(root_id)
    return ids


def is_in_subtree(db: Session, ancestor_id: int, user_id: int) -> bool:
    """True if user_id is strictly below ancestor_id."""
    return user_id in subtree_ids(db, ancestor_id)


def ancestor_ids(db: Session, user_id: int, include_self: bool = False) -> set[int]:
    """IDs of everyone strictly above user_id (their manager chain), via a
    recursive CTE walking up manager_id. Mirrors subtree_ids in the other
    direction: used to find which team an equipment item is designated to."""
    node = select(User.id, User.manager_id).where(User.id == user_id)
    tree = node.cte(name="ancestry", recursive=True)
    tree = tree.union_all(
        select(User.id, User.manager_id).where(User.id == tree.c.manager_id)
    )
    ids = set(db.scalars(select(tree.c.id).where(tree.c.id != user_id)))
    if include_self:
        ids.add(user_id)
    return ids


def position_subordinate_ids(db: Session, user_id: int) -> set[int]:
    """Occupants of every position strictly below any position this user
    occupies — the org *chart* descent, role-template seats included.

    This is what makes tasking team-scoped: a team's seats (lead / coach /
    member) chain under that team's own node, so a Sumo 1 lead reaches Sumo 1's
    members and nothing in Sumo 2, however powerful either side's access level
    is. manager_id can't express this — role-template seats deliberately never
    set it (see positions/service.resync_managers), they're a hat, not a
    reporting line."""
    my_positions = select(PositionOccupant.position_id).where(
        PositionOccupant.user_id == user_id
    )
    base = select(Position.id).where(Position.parent_id.in_(my_positions))
    tree = base.cte(name="pos_below", recursive=True)
    tree = tree.union_all(select(Position.id).where(Position.parent_id == tree.c.id))
    return set(
        db.scalars(
            select(PositionOccupant.user_id).where(
                PositionOccupant.position_id.in_(select(tree.c.id))
            )
        )
    )


def managed_team_member_ids(db: Session, user: User) -> set[int]:
    """Everyone on an event team this user leads by seat. Covers the case where
    the org has no member-seat role template, so a team's members have no
    position of their own for position_subordinate_ids to find — they're still
    that team's people, and their lead can still task them."""
    from app.domains.events.service import (
        can_manage_team,
        team_member_user_ids,
        user_event_team_ids,
    )
    from app.domains.events.models import EventTeam

    out: set[int] = set()
    for team_id in user_event_team_ids(db, user.id):
        team = db.get(EventTeam, team_id)
        if team is None or team.deleted_at is not None:
            continue
        if can_manage_team(db, user, team):
            out |= team_member_user_ids(db, team.id)
    return out


def taskable_user_ids(db: Session, user: User) -> set[int]:
    """Everyone this user may assign a task to. A structural connection in the
    org must exist — one of:

    - themselves;
    - their manager_id subtree (their real reporting line);
    - anyone occupying a seat below one of theirs in the org chart (this is the
      team path — see position_subordinate_ids);
    - members of an event team they lead by seat.

    Access level alone grants nothing here: being higher-ranked than someone in
    another team is not a connection. The one escape hatch is the
    `tasks.assign_any` privilege, handled by can_assign_task — the ladder's
    admin-editable "task anyone" switch."""
    ids = visible_user_ids(db, user)
    ids |= position_subordinate_ids(db, user.id)
    ids |= managed_team_member_ids(db, user)
    return ids


def can_assign_task(db: Session, assigner: User, assignee: User) -> bool:
    """Tasks flow down a real org connection (see taskable_user_ids), or to
    oneself. `tasks.assign_any` lifts the structural limit entirely."""
    if not assignee.is_active:
        return False
    if assignee.id == assigner.id:
        return True
    if access.has_privilege(db, assigner, "tasks.assign_any"):
        return True
    return assignee.id in taskable_user_ids(db, assigner)


def can_send_request(db: Session, requester: User, recipient: User) -> bool:
    """Requests flow up or across: any active user who works with tasks and
    whom the requester cannot task directly."""
    if recipient.id == requester.id or not recipient.is_active:
        return False
    if not access.has_privilege(db, recipient, "tasks.use"):
        return False
    return recipient.id not in taskable_user_ids(db, requester)


def can_review_task(db: Session, user: User, assigner_id: int) -> bool:
    """Approve / request revision: the assigner or anyone above them."""
    if access.is_top(db, user):
        return True
    return user.id == assigner_id or is_in_subtree(db, user.id, assigner_id)


def visible_user_ids(db: Session, user: User) -> set[int]:
    """Self plus everyone in the user's subtree — the visibility scope."""
    return subtree_ids(db, user.id, include_self=True)


def assert_no_cycle(db: Session, user_id: int, new_manager_id: int | None) -> bool:
    """A user's manager must not be the user or anyone in their subtree."""
    if new_manager_id is None:
        return True
    if new_manager_id == user_id:
        return False
    return new_manager_id not in subtree_ids(db, user_id)
