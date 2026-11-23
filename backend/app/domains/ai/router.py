"""AI assistant API.

Two kinds of callers:
- the portal UI (session cookie): conversations, streaming chat, confirm/reject,
  semantic search, minting a token to connect a terminal Claude Code;
- the MCP server (Bearer AI token): list and call tools as that user."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import BASE_DIR, settings
from app.core.database import get_db
from app.domains.access import service as access
from app.domains.ai import prompts, search as semantic, service
from app.domains.ai.models import (
    ActionStatus,
    AiConversation,
    AiFile,
    AiMessage,
    AiPendingAction,
    ConversationMode,
)
from app.domains.ai.tools import catalog
from app.domains.auth.deps import DB, CurrentUser
from app.domains.users.models import User

router = APIRouter(prefix="/ai", tags=["ai"])


# ---------------------------------------------------------------- provider
_provider_override = None
_running: set[int] = set()  # user ids with a run in flight


def set_provider(provider) -> None:
    """Tests inject a FakeProvider."""
    global _provider_override
    _provider_override = provider


def get_provider():
    if _provider_override is not None:
        return _provider_override
    if settings.ai_provider == "claude_code":
        if settings.cookie_secure:
            # cookie_secure is only on behind real HTTPS (the VM). A personal
            # Claude subscription must never serve other members from there.
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                                "The Claude Code provider is for local use only")
        from app.domains.ai.providers.claude_code import ClaudeCodeProvider

        return ClaudeCodeProvider()
    if settings.ai_provider == "chain":
        from app.domains.ai.providers import chain

        if not chain.configured_links():
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                                "No AI model is configured (set AI_CHAIN and an API key)")
        return chain.ChainProvider()
    raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                        "The AI assistant is not configured (set AI_PROVIDER)")


# ------------------------------------------------------------ token auth
def token_user(
    db: Annotated[Session, Depends(get_db)],
    authorization: Annotated[str | None, Header()] = None,
) -> tuple[User, int | None]:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing AI token")
    return service.resolve_token(db, authorization.split(" ", 1)[1].strip())


TokenUser = Annotated[tuple[User, int | None], Depends(token_user)]


class ToolCall(BaseModel):
    arguments: dict[str, Any] = Field(default_factory=dict)


@router.get("/tools")
def list_tools(auth: TokenUser) -> list[dict]:
    return catalog()


@router.get("/history")
def conversation_history(auth: TokenUser, db: DB) -> list[dict]:
    """The token's conversation before its latest user message (which the
    provider gets on its own, with any portal notes folded in)."""
    user, conversation_id = auth
    conv = db.get(AiConversation, conversation_id) if conversation_id is not None else None
    if conv is None or conv.user_id != user.id:
        return []
    rows = list(conv.messages)
    last_user = max((i for i, m in enumerate(rows) if m.role == "user"), default=len(rows))
    return [{"role": m.role, "text": m.text, "tools": json.loads(m.tools or "[]")} for m in rows[:last_user]]


@router.post("/tools/{name}")
def run_tool(name: str, payload: ToolCall, auth: TokenUser, db: DB) -> Any:
    user, conversation_id = auth
    return service.call_tool(db, user, name, payload.arguments, conversation_id)


# ----------------------------------------------------------------- status
@router.get("/status")
def ai_status(db: DB, user: CurrentUser) -> dict:
    service.require_ai(db, user)
    out = {"provider": settings.ai_provider, "embedder": settings.ai_embedder,
           "models": {"assistant": settings.ai_model_assistant, "planner": settings.ai_model_planner}}
    if settings.ai_provider == "chain":
        from app.domains.ai.providers import chain

        links = chain.chain_status()
        out["chain"] = links
        out["models"] = {"assistant": links[0]["link"] if links else "", "planner": links[0]["link"] if links else ""}
        configured = bool(links)
    else:
        configured = settings.ai_provider == "claude_code" and not settings.cookie_secure
    out["available"] = configured or _provider_override is not None
    return out


# ---------------------------------------------------------- conversations
class ConversationCreate(BaseModel):
    mode: ConversationMode = ConversationMode.ASSISTANT
    title: str | None = Field(default=None, max_length=255)


def _conv_out(c: AiConversation) -> dict:
    return {"id": c.id, "title": c.title, "mode": c.mode, "created_at": c.created_at, "updated_at": c.updated_at}


def _action_out(a: AiPendingAction) -> dict:
    return {"id": a.id, "conversation_id": a.conversation_id, "tool": a.tool, "summary": a.summary,
            "status": a.status, "input": json.loads(a.input),
            "result": json.loads(a.result) if a.result else None, "created_at": a.created_at}


def _get_conv(db: Session, user: User, conversation_id: int) -> AiConversation:
    conv = db.get(AiConversation, conversation_id)
    if conv is None or conv.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    return conv


@router.get("/conversations")
def list_conversations(db: DB, user: CurrentUser) -> list[dict]:
    service.require_ai(db, user)
    rows = db.scalars(select(AiConversation).where(AiConversation.user_id == user.id)
                      .order_by(AiConversation.updated_at.desc()))
    return [_conv_out(c) for c in rows]


@router.post("/conversations", status_code=status.HTTP_201_CREATED)
def create_conversation(payload: ConversationCreate, db: DB, user: CurrentUser) -> dict:
    service.require_ai(db, user)
    conv = AiConversation(user_id=user.id, mode=payload.mode,
                          title=payload.title or ("New plan" if payload.mode == "planner" else "New conversation"))
    db.add(conv)
    db.commit()
    return _conv_out(conv)


@router.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: int, db: DB, user: CurrentUser) -> dict:
    service.require_ai(db, user)
    conv = _get_conv(db, user, conversation_id)
    actions = db.scalars(select(AiPendingAction).where(AiPendingAction.conversation_id == conv.id)
                         .order_by(AiPendingAction.id))
    return {**_conv_out(conv),
            "messages": [{"id": m.id, "role": m.role, "text": m.text, "tools": json.loads(m.tools),
                          "created_at": m.created_at} for m in conv.messages],
            "actions": [_action_out(a) for a in actions],
            "files": [_file_out(f) for f in db.scalars(
                select(AiFile).where(AiFile.conversation_id == conv.id).order_by(AiFile.id))]}


def _file_out(f: AiFile) -> dict:
    return {"id": f.id, "filename": f.filename, "media_type": f.media_type, "size": f.size,
            "conversation_id": f.conversation_id, "created_at": f.created_at,
            "download": f"/api/ai/files/{f.id}"}


@router.get("/files")
def list_files(db: DB, user: CurrentUser) -> list[dict]:
    service.require_ai(db, user)
    rows = db.scalars(select(AiFile).where(AiFile.user_id == user.id).order_by(AiFile.id.desc()).limit(100))
    return [_file_out(f) for f in rows]


@router.get("/files/{file_id}")
def download_file(file_id: int, db: DB, user: CurrentUser) -> Response:
    service.require_ai(db, user)
    f = db.get(AiFile, file_id)
    if f is None or f.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")
    safe = f.filename.replace('"', "")
    return Response(content=f.data, media_type=f.media_type,
                    headers={"Content-Disposition": f'attachment; filename="{safe}"'})


@router.delete("/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_file(file_id: int, db: DB, user: CurrentUser) -> None:
    f = db.get(AiFile, file_id)
    if f is None or f.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")
    db.delete(f)
    db.commit()


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(conversation_id: int, db: DB, user: CurrentUser) -> None:
    conv = _get_conv(db, user, conversation_id)
    for a in db.scalars(select(AiPendingAction).where(
            AiPendingAction.conversation_id == conv.id, AiPendingAction.status == ActionStatus.PENDING)):
        a.status = ActionStatus.REJECTED
    db.delete(conv)
    db.commit()


class MessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=20000)


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, default=str, ensure_ascii=False)}\n\n"


@router.post("/conversations/{conversation_id}/messages")
async def send_message(conversation_id: int, payload: MessageIn, db: DB, user: CurrentUser) -> StreamingResponse:
    """Run one turn and stream it as server-sent events. The turn's text and
    tool activity are saved when it ends; proposed actions are already saved
    by the tool endpoint and are re-sent as an `actions` event."""
    service.require_ai(db, user)
    conv = _get_conv(db, user, conversation_id)
    provider = get_provider()
    if user.id in _running:
        raise HTTPException(status.HTTP_409_CONFLICT, "The assistant is still answering your last message")
    # Fold in notes (confirmations/rejections) the agent hasn't seen yet.
    last_user = max((m.id for m in conv.messages if m.role == "user"), default=0)
    notes = [m.text for m in conv.messages if m.role == "note" and m.id > last_user]
    text = payload.text if not notes else "[Portal notes since your last turn]\n" + "\n".join(notes) + "\n\n" + payload.text
    db.add(AiMessage(conversation_id=conv.id, role="user", text=payload.text))
    if conv.title in ("New conversation", "New plan"):
        conv.title = payload.text[:80]
    db.commit()
    token = service.mint_token(db, user, conv.id, label="chat")
    system = prompts.PLANNER if conv.mode == ConversationMode.PLANNER else prompts.BASE
    conv_id, user_id, session_id, mode = conv.id, user.id, conv.provider_session_id, conv.mode
    before = {a.id for a in db.scalars(select(AiPendingAction.id).where(AiPendingAction.conversation_id == conv_id))}

    async def stream():
        _running.add(user_id)
        reply, tools, new_session = [], [], session_id
        try:
            async for event in provider.run(text=text, mode=mode, token=token, session_id=session_id, system=system):
                if event["type"] == "session":
                    new_session = event["id"]
                    continue
                if event["type"] == "text":
                    reply.append(event["text"])
                elif event["type"] == "tool":
                    if reply and not reply[-1].endswith("\n"):
                        reply.append("\n\n")  # text before and after a tool call are separate paragraphs
                    tools.append({"name": event["name"], "input": event["input"]})
                elif event["type"] == "tool_result" and tools:
                    tools[-1]["result"] = event["result"]
                    if isinstance(event["result"], dict) and event["result"].get("proposed"):
                        yield _sse({"type": "actions"})
                if event["type"] == "done":
                    break
                yield _sse(event)
        finally:
            _running.discard(user_id)
            db.expire_all()
            c = db.get(AiConversation, conv_id)
            if c is not None:
                c.provider_session_id = new_session
                c.updated_at = datetime.now(timezone.utc)
                db.add(AiMessage(conversation_id=conv_id, role="assistant", text="".join(reply),
                                 tools=json.dumps(tools, default=str)))
                db.commit()
            new = [_action_out(a) for a in db.scalars(select(AiPendingAction).where(
                AiPendingAction.conversation_id == conv_id).order_by(AiPendingAction.id)) if a.id not in before]
        yield _sse({"type": "done", "new_actions": new})

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---------------------------------------------------------------- actions
class ActionIds(BaseModel):
    ids: list[int] = Field(min_length=1)


@router.get("/actions")
def list_actions(db: DB, user: CurrentUser, status_filter: str = "pending") -> list[dict]:
    service.require_ai(db, user)
    q = select(AiPendingAction).where(AiPendingAction.user_id == user.id)
    if status_filter != "all":
        q = q.where(AiPendingAction.status == status_filter)
    return [_action_out(a) for a in db.scalars(q.order_by(AiPendingAction.id.desc()).limit(200))]


@router.post("/actions/confirm")
def confirm_actions(payload: ActionIds, db: DB, user: CurrentUser) -> dict:
    return service.confirm(db, user, payload.ids)


@router.post("/actions/reject", status_code=status.HTTP_204_NO_CONTENT)
def reject_actions(payload: ActionIds, db: DB, user: CurrentUser) -> None:
    service.require_ai(db, user)
    service.reject(db, user, payload.ids)


# ----------------------------------------------- connect a terminal Claude
@router.post("/connect")
def connect_terminal(db: DB, user: CurrentUser) -> dict:
    """Mint a token for the user's own terminal Claude Code. Shown once."""
    service.require_ai(db, user)
    token = service.mint_token(db, user, None, label="terminal")
    python = str(BASE_DIR / ".venv" / "bin" / "python3")
    env = {"PORTAL_URL": settings.ai_portal_url, "PORTAL_AI_TOKEN": token, "PYTHONPATH": str(BASE_DIR)}
    return {
        "token": token, "expires_in_hours": settings.ai_token_ttl_hours,
        "mcp_json": {"mcpServers": {"portal": {"type": "stdio", "command": python,
                                                "args": ["-m", "app.domains.ai.mcp_server"], "env": env}}},
        "command": " ".join(["claude", "mcp", "add", "portal", "--scope", "user",
                             *[f"-e {k}={v}" for k, v in env.items()], "--", python, "-m", "app.domains.ai.mcp_server"]),
    }


# ----------------------------------------------------------------- search
@router.get("/search")
async def search(db: DB, user: CurrentUser, q: str = Query(min_length=1, max_length=200),
                 types: str | None = None, limit: int = Query(default=20, ge=1, le=100)) -> list[dict]:
    """Semantic search; no ai.use needed — each type is filtered by its own view privilege."""
    wanted = [t for t in (types or "").split(",") if t] or None
    # embedding is CPU work; keep the event loop free
    return await asyncio.to_thread(semantic.search, db, user, q, wanted, limit)


@router.post("/inventory-aliases")
async def fill_inventory_aliases(db: DB, user: CurrentUser) -> dict:
    """Have the local Claude Code write 'also known as' names for items that
    have none (ai.admin; local provider only). Slow: about a minute per 60 items."""
    access.require_privilege(db, user, "ai.admin")
    if settings.ai_provider != "claude_code":
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Alias filling needs the local Claude Code provider")
    get_provider()  # same local-only guard as the chat
    from app.domains.ai.aliases import fill_missing

    return await fill_missing(db)


@router.post("/reindex")
def reindex(db: DB, user: CurrentUser) -> dict:
    access.require_privilege(db, user, "ai.admin")
    return semantic.reindex(db, user)
