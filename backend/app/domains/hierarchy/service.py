"""Org-hierarchy traversal and the permission predicates built on it.

The hierarchy is data-driven: users.manager_id forms a tree. Every permission
below derives from that tree at query time, so moving a person in the tree
instantly changes who can see and task them. Multi-role users occupy a single
node; their effective reach is whatever the tree gives that node (union by
construction).
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

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


def can_assign_task(db: Session, assigner: User, assignee: User) -> bool:
    """Tasks flow down: only into the assigner's strict subtree.
    The technical admin bypasses hierarchy checks."""
    if not assignee.is_active:
        return False
    if assigner.is_admin:
        return assigner.id != assignee.id
    return is_in_subtree(db, assigner.id, assignee.id)


def can_send_request(db: Session, requester: User, recipient: User) -> bool:
    """Requests flow up or across: any active staff user the requester cannot
    task directly (not themselves, not in their subtree)."""
    if recipient.id == requester.id or not recipient.is_active:
        return False
    if not recipient.is_staff:
        return False
    return not is_in_subtree(db, requester.id, recipient.id)


def can_review_task(db: Session, user: User, assigner_id: int) -> bool:
    """Approve / request revision: the assigner or anyone above them."""
    if user.is_admin:
        return True
    return user.id == assigner_id or is_in_subtree(db, user.id, assigner_id)


def visible_user_ids(db: Session, user: User) -> set[int]:
    """Self plus everyone in the user's subtree — the visibility scope."""
    return subtree_ids(db, user.id, include_self=True)


def is_org_manager(actor: User) -> bool:
    """Full org-editing rights over the whole hierarchy: the technical admin and
    the CEO. (The CEO still can't grant the admin role — that's admin-only.)"""
    return actor.is_admin or actor.is_ceo


def can_manage_user(db: Session, actor: User, target: User) -> bool:
    """Who may edit a user: admin and CEO over the whole org; any other staff
    member over their own subtree. Editing an admin account stays admin-only."""
    if actor.is_admin:
        return True
    if target.is_admin:
        return False
    if actor.is_ceo:
        return True
    if not actor.is_staff:
        return False
    return target.id in subtree_ids(db, actor.id)


def can_place_under(db: Session, actor: User, manager_id: int | None) -> bool:
    """Where a person may be attached: admin/CEO anywhere in the org; other staff
    under themselves or their subtree. Non-admins can't create rootless users."""
    if actor.is_admin:
        return True
    if manager_id is None:
        return False
    if actor.is_ceo:
        return True
    return manager_id == actor.id or manager_id in subtree_ids(db, actor.id)


def assert_no_cycle(db: Session, user_id: int, new_manager_id: int | None) -> bool:
    """A user's manager must not be the user or anyone in their subtree."""
    if new_manager_id is None:
        return True
    if new_manager_id == user_id:
        return False
    return new_manager_id not in subtree_ids(db, user_id)
