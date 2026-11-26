"""AI assistant storage: conversations, their messages, the actions the AI
proposed (which only run once a person confirms them), the short-lived tokens
the MCP server uses to call tools as a user, and the semantic-search vectors."""

from datetime import datetime, timezone
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ConversationMode(StrEnum):
    ASSISTANT = "assistant"  # quick commands and lookups
    PLANNER = "planner"  # heavier model + web research


class ActionStatus(StrEnum):
    PENDING = "pending"
    DONE = "done"
    REJECTED = "rejected"
    FAILED = "failed"


class AiConversation(Base):
    __tablename__ = "ai_conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(255), default="New conversation")
    mode: Mapped[str] = mapped_column(String(20), default=ConversationMode.ASSISTANT)
    # The Claude Code session this conversation resumes (claude_code provider).
    provider_session_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    messages: Mapped[list["AiMessage"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", order_by="AiMessage.id"
    )


class AiMessage(Base):
    __tablename__ = "ai_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("ai_conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(20))  # user | assistant | tool | note
    text: Mapped[str] = mapped_column(Text, default="")
    # Tool activity for this turn: [{"name", "input", "result"}] as JSON text.
    tools: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    conversation: Mapped[AiConversation] = relationship(back_populates="messages")


class AiPendingAction(Base):
    """A write the AI wants to make. Nothing happens until the owner confirms."""

    __tablename__ = "ai_pending_actions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("ai_conversations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    tool: Mapped[str] = mapped_column(String(60))
    # channel the AI used: "assistant" | "mcp" | "agent:<name>" (see AuditLog.via)
    via: Mapped[str] = mapped_column(String(120), default="assistant")
    input: Mapped[str] = mapped_column(Text)  # validated JSON
    summary: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default=ActionStatus.PENDING, index=True)
    result: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON on success, message on failure
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AiFile(Base):
    """A spreadsheet or PDF the assistant generated, downloadable only by the
    person whose session made it."""

    __tablename__ = "ai_files"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("ai_conversations.id", ondelete="CASCADE"), nullable=True, index=True
    )
    filename: Mapped[str] = mapped_column(String(200))
    media_type: Mapped[str] = mapped_column(String(120))
    size: Mapped[int] = mapped_column(Integer, default=0)
    data: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class AiToken(Base):
    """Lets the MCP server call /api/ai/tools/* as one user. Only the SHA-256
    of the token is stored; it is valid for nothing else in the API."""

    __tablename__ = "ai_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("ai_conversations.id", ondelete="CASCADE"), nullable=True
    )
    label: Mapped[str] = mapped_column(String(100), default="")
    # NULL = a personal agent connection: valid until its owner revokes it
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class AiEmbedding(Base):
    """One entity's vector. text_hash detects when the source text changed."""

    __tablename__ = "ai_embeddings"
    __table_args__ = (UniqueConstraint("entity_type", "entity_id", "model"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(30), index=True)
    entity_id: Mapped[int] = mapped_column(Integer)
    model: Mapped[str] = mapped_column(String(100))
    text_hash: Mapped[str] = mapped_column(String(64))
    text: Mapped[str] = mapped_column(Text)
    vector: Mapped[str] = mapped_column(Text)  # JSON list[float], L2-normalised
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class OAuthClient(Base):
    """An outside AI agent registered itself (RFC 7591 dynamic registration)
    so it can ask people to connect it to the portal's MCP endpoint. Public
    client: no secret, PKCE protects the code exchange."""

    __tablename__ = "oauth_clients"

    client_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    redirect_uris: Mapped[str] = mapped_column(Text)  # JSON list
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class OAuthCode(Base):
    """A one-time authorization code a person granted an agent on the consent
    page; exchanged (with the PKCE verifier) for an agent token."""

    __tablename__ = "oauth_codes"

    id: Mapped[int] = mapped_column(primary_key=True)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    client_id: Mapped[str] = mapped_column(ForeignKey("oauth_clients.client_id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    redirect_uri: Mapped[str] = mapped_column(Text)
    code_challenge: Mapped[str] = mapped_column(String(128))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
