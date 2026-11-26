import json

from sqlalchemy.orm import Session

from app.domains.audit.models import AuditLog

# Key in Session.info under which the AI assistant marks the change it is
# making right now, so every entry written meanwhile records that the AI did
# it, through what, and who approved it — see app.domains.ai.service.
AI_STAMP = "ai_audit_stamp"


def ai_stamp(db: Session) -> dict | None:
    return db.info.get(AI_STAMP)


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
    stamp = ai_stamp(db)
    if stamp is not None:
        entry.via = stamp["via"]
        entry.approved_by_id = stamp["approved_by_id"]
        entry.ai_action_id = stamp["action_id"]
        stamp["rows"] += 1
    db.add(entry)
    return entry
