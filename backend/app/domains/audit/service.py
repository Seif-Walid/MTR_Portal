import json

from sqlalchemy.orm import Session

from app.domains.audit.models import AuditLog


def log(
    db: Session,
    actor_id: int | None,
    domain: str,
    action: str,
    entity_type: str,
    entity_id: int | None,
    detail: dict | None = None,
) -> AuditLog:
    """Record an audit entry. Caller owns the commit (mirrors notify())."""
    entry = AuditLog(
        actor_id=actor_id,
        domain=domain,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        detail=json.dumps(detail or {}, default=str),
    )
    db.add(entry)
    return entry
