"""AI tokens, running tools, and the propose → confirm flow."""

from __future__ import annotations

import hashlib
import html
import json
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.domains.access import service as access
from app.domains.ai.models import ActionStatus, AiConversation, AiMessage, AiPendingAction, AiToken
from app.domains.ai.tools import TOOLS, _json
from app.domains.audit.service import log as audit_log
from app.domains.users.models import User


# ------------------------------------------------------------------ tokens
def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


AGENT_LABEL = "agent:"  # label prefix of personal agent connections (no expiry)
_TOUCH_EVERY = timedelta(minutes=5)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def mint_token(db: Session, user: User, conversation_id: int | None = None, label: str = "",
               expires: bool = True) -> tuple[str, AiToken]:
    """A random token sent as a bearer; only the hash is kept. `expires=False`
    is a personal agent connection that lasts until it is revoked."""
    token = "mtrai_" + secrets.token_urlsafe(32)
    rec = AiToken(
        token_hash=_digest(token), user_id=user.id, conversation_id=conversation_id, label=label,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=settings.ai_token_ttl_hours) if expires else None,
    )
    db.add(rec)
    db.commit()
    return token, rec


def resolve_token(db: Session, token: str) -> tuple[User, int | None]:
    rec = db.scalar(select(AiToken).where(AiToken.token_hash == _digest(token)))
    if rec is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid AI token")
    now = datetime.now(timezone.utc)
    if rec.expires_at is not None and _aware(rec.expires_at) < now:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "AI token expired")
    user = db.get(User, rec.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account disabled")
    require_ai(db, user)
    if rec.last_used_at is None or now - _aware(rec.last_used_at) > _TOUCH_EVERY:
        rec.last_used_at = now
        db.commit()
    return user, rec.conversation_id


def agent_connections(db: Session, user: User) -> list[AiToken]:
    return list(db.scalars(
        select(AiToken).where(AiToken.user_id == user.id, AiToken.expires_at.is_(None),
                              AiToken.label.startswith(AGENT_LABEL))
        .order_by(AiToken.created_at.desc())
    ))


def revoke_connection(db: Session, user: User, token_id: int) -> None:
    rec = db.get(AiToken, token_id)
    if rec is None or rec.user_id != user.id or rec.expires_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Connection not found")
    db.delete(rec)
    db.commit()


def require_ai(db: Session, user: User) -> None:
    access.require_privilege(db, user, "ai.use")


# --------------------------------------------------------------- tool calls
def _error(exc: Exception) -> dict:
    if isinstance(exc, HTTPException):
        return {"error": exc.detail, "status": exc.status_code}
    if isinstance(exc, ValidationError):
        return {"error": "Invalid input", "details": json.loads(exc.json(include_url=False))}
    return {"error": str(exc)}


def _pending_chain(db: Session, user: User, conversation_id: int | None) -> list[AiPendingAction]:
    q = select(AiPendingAction).where(
        AiPendingAction.user_id == user.id, AiPendingAction.status == ActionStatus.PENDING)
    if conversation_id is not None:
        q = q.where(AiPendingAction.conversation_id == conversation_id)
    return list(db.scalars(q.order_by(AiPendingAction.id)))


def _fresh(db: Session, user: User) -> User:
    """Start from a clean session: a rolled-back dry run can leave rows with
    reused ids behind in the identity map, which a later flush trips over."""
    uid = user.id
    db.expunge_all()
    return db.get(User, uid)


def _execute(db: Session, user: User, actions: list[tuple[int, str, dict]]) -> dict[int, dict]:
    """Run (id, tool, input) in order, threading results so later actions can
    reference earlier ones. Raises on the first failure; never commits."""
    refs: dict[int, dict] = {}
    for action_id, name, raw in actions:
        tool = TOOLS[name]
        try:
            refs[action_id] = _json(tool.run(db, user, tool.input_model.model_validate(raw), refs))
        except Exception as exc:  # noqa: BLE001 - annotate which action failed
            exc.ai_action_id = action_id  # type: ignore[attr-defined]
            raise
    return refs


def _unescape(value):
    """Models sometimes HTML-escape their arguments ("R&amp;D"); store plain text."""
    if isinstance(value, str):
        return html.unescape(value)
    if isinstance(value, list):
        return [_unescape(v) for v in value]
    if isinstance(value, dict):
        return {k: _unescape(v) for k, v in value.items()}
    return value


def call_tool(db: Session, user: User, name: str, raw: dict, conversation_id: int | None) -> dict:
    tool = TOOLS.get(name)
    if tool is None:
        return {"error": f"Unknown tool {name}"}
    try:
        inp = tool.input_model.model_validate(_unescape(raw or {}))
    except ValidationError as exc:
        return _error(exc)
    if tool.kind == "read":
        try:
            if tool.needs_conversation:
                return _json(tool.run(db, user, inp, conversation_id))
            return _json(tool.run(db, user, inp))
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            return _error(exc)
    # write: dry-run this action after the conversation's other pending ones
    # (so "4 more of the same part" or "the team from #12" is checked for
    # real), roll everything back, then store it as pending.
    user = _fresh(db, user)
    chain = [(a.id, a.tool, json.loads(a.input)) for a in _pending_chain(db, user, conversation_id)]
    chain.append((0, name, inp.model_dump(mode="json")))
    try:
        db.info["ai_dry_run"] = True
        _execute(db, user, chain)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        failed = getattr(exc, "ai_action_id", 0)
        out = _error(exc)
        if failed:
            out["error"] = f"Earlier pending action #{failed} no longer works: {out['error']}"
        out["note"] = "Not proposed. Fix the input (or ask the user) and try again."
        return out
    db.rollback()
    user = _fresh(db, user)
    summary = tool.summarize(db, inp) if tool.summarize else name
    action = AiPendingAction(
        user_id=user.id, conversation_id=conversation_id, tool=name,
        input=json.dumps(inp.model_dump(mode="json")), summary=summary,
    )
    db.add(action)
    db.commit()
    return {"proposed": True, "action_id": action.id, "summary": summary,
            "note": "Awaiting the user's confirmation in the portal. Do not claim it is done."}


# ----------------------------------------------------------- confirm/reject
def _owned(db: Session, user: User, ids: list[int]) -> list[AiPendingAction]:
    rows = list(db.scalars(select(AiPendingAction).where(AiPendingAction.id.in_(ids)).order_by(AiPendingAction.id)))
    if len(rows) != len(set(ids)) or any(a.user_id != user.id for a in rows):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Action not found")
    if any(a.status != ActionStatus.PENDING for a in rows):
        raise HTTPException(status.HTTP_409_CONFLICT, "Some of these actions were already decided")
    return rows


def _note(db: Session, conversation_id: int | None, text: str) -> None:
    if conversation_id is not None and db.get(AiConversation, conversation_id) is not None:
        db.add(AiMessage(conversation_id=conversation_id, role="note", text=text))


def confirm(db: Session, user: User, ids: list[int]) -> dict:
    """All-or-nothing: the chosen actions run in id order in one transaction."""
    require_ai(db, user)
    user = _fresh(db, user)
    rows = _owned(db, user, ids)
    try:
        db.info["ai_dry_run"] = False
        results = _execute(db, user, [(a.id, a.tool, json.loads(a.input)) for a in rows])
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        failed_id = getattr(exc, "ai_action_id", None)
        detail = _error(exc)["error"]
        failed = db.get(AiPendingAction, failed_id) if failed_id else None
        if failed is not None:
            failed.result = json.dumps({"error": detail})
            _note(db, failed.conversation_id, f"Confirming #{failed.id} failed, nothing was changed: {detail}")
            db.commit()
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"Action #{failed_id} failed, nothing was changed: {detail}") from exc
    now = datetime.now(timezone.utc)
    for a in rows:
        a.status, a.result, a.decided_at = ActionStatus.DONE, json.dumps(results[a.id]), now
        audit_log(db, user.id, "ai", "action_confirmed", "ai_action", a.id,
                  {"tool": a.tool, "summary": a.summary, "conversation": a.conversation_id, "via": "ai"})
    for conv in {a.conversation_id for a in rows}:
        done = [a for a in rows if a.conversation_id == conv]
        # first line for people, second line (ids created) for the agent
        _note(db, conv, "Confirmed and done: " + "; ".join(f"#{a.id} {a.summary}" for a in done)
              + "\nResults: " + "; ".join(f"#{a.id} → {a.result}" for a in done))
    db.commit()
    return {"done": [{"action_id": a.id, "result": results[a.id]} for a in rows]}


def reject(db: Session, user: User, ids: list[int]) -> None:
    rows = _owned(db, user, ids)
    now = datetime.now(timezone.utc)
    for a in rows:
        a.status, a.decided_at = ActionStatus.REJECTED, now
    for conv in {a.conversation_id for a in rows}:
        _note(db, conv, "Rejected by the user: " + "; ".join(f"#{a.id} {a.summary}" for a in rows if a.conversation_id == conv))
    db.commit()
