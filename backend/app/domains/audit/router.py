from fastapi import APIRouter
from sqlalchemy import func, select

from app.domains.access import service as access
from app.domains.audit.models import AuditLog
from app.domains.auth.deps import DB, CurrentUser
from app.domains.users.models import User

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("")
def list_audit_log(
    db: DB,
    user: CurrentUser,
    domain: str | None = None,
    entity_type: str | None = None,
    entity_id: int | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Filter by domain, entity type, or a specific entity id. Paged
    server-side: `total` counts every matching row so the client can page
    through the whole log, and `domains` lists every domain that has entries
    (the filter options) regardless of the current filter."""
    access.require_privilege(db, user, "audit.view")
    filters = []
    if domain:
        filters.append(AuditLog.domain == domain)
    if entity_type:
        filters.append(AuditLog.entity_type == entity_type)
    if entity_id is not None:
        filters.append(AuditLog.entity_id == entity_id)
    total = db.scalar(select(func.count()).select_from(AuditLog).where(*filters))
    rows = db.scalars(
        select(AuditLog)
        .where(*filters)
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .offset(max(offset, 0))
        .limit(max(1, min(limit, 500)))
    ).all()
    actor_ids = {r.actor_id for r in rows if r.actor_id}
    actors = (
        {u.id: u.full_name for u in db.scalars(select(User).where(User.id.in_(actor_ids)))}
        if actor_ids else {}
    )
    domains = sorted(db.scalars(select(AuditLog.domain).distinct()))
    return {
        "items": [
            {
                "id": r.id,
                "actor": actors.get(r.actor_id, "—"),
                "domain": r.domain,
                "action": r.action,
                "entity_type": r.entity_type,
                "entity_id": r.entity_id,
                "detail": r.detail,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ],
        "total": total,
        "domains": domains,
    }
