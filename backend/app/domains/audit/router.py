from fastapi import APIRouter
from sqlalchemy import select

from app.domains.audit.models import AuditLog
from app.domains.auth.deps import DB, AdminUser
from app.domains.users.models import User

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("")
def list_audit_log(
    db: DB,
    _: AdminUser,
    domain: str | None = None,
    entity_type: str | None = None,
    entity_id: int | None = None,
    limit: int = 100,
) -> list[dict]:
    """Admin-only. Filter by domain (users|inventory|competitions), entity
    type, or a specific entity id."""
    query = select(AuditLog)
    if domain:
        query = query.where(AuditLog.domain == domain)
    if entity_type:
        query = query.where(AuditLog.entity_type == entity_type)
    if entity_id is not None:
        query = query.where(AuditLog.entity_id == entity_id)
    rows = db.scalars(query.order_by(AuditLog.created_at.desc()).limit(min(limit, 500)))
    out = []
    for r in rows:
        actor = db.get(User, r.actor_id) if r.actor_id else None
        out.append({
            "id": r.id,
            "actor": actor.full_name if actor else "—",
            "domain": r.domain,
            "action": r.action,
            "entity_type": r.entity_type,
            "entity_id": r.entity_id,
            "detail": r.detail,
            "created_at": r.created_at.isoformat(),
        })
    return out
