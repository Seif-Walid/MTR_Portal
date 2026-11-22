"""ai_assistant: conversations, pending actions, tokens, embeddings

The AI assistant (local Claude Code over the portal MCP server):
- ai_conversations / ai_messages: chat history per user
- ai_pending_actions: writes the AI proposed; nothing runs until confirmed
- ai_tokens: short-lived tokens the MCP server uses to call tools as a user
- ai_embeddings: semantic-search vectors (JSON, so SQLite and Postgres match)
- inventory_allocations.event_team_id: allocate to a specific event team
- inventory_items.aliases: other names a part goes by, for search

Two new privileges: ai.use goes to Board and Lead, ai.admin to Board.

Revision ID: a7c3e9f1b5d2
Revises: f2c8a4d6b1e3
Create Date: 2026-11-17

"""
import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a7c3e9f1b5d2"
down_revision: Union[str, None] = "f2c8a4d6b1e3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

GRANTS = {
    "Board": ["ai.use", "ai.admin"],
    "Lead": ["ai.use"],
}


def _grant(add: bool) -> None:
    bind = op.get_bind()
    levels = sa.table("access_levels", sa.column("id"), sa.column("name"), sa.column("privileges"))
    for lid, name, privs in bind.execute(sa.select(levels.c.id, levels.c.name, levels.c.privileges)):
        new = set(GRANTS.get(name, []))
        if not new:
            continue
        keys = set(json.loads(privs or "[]"))
        keys = keys | new if add else keys - new
        bind.execute(levels.update().where(levels.c.id == lid).values(privileges=json.dumps(sorted(keys))))


def upgrade() -> None:
    op.create_table(
        "ai_conversations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("mode", sa.String(20), nullable=False),
        sa.Column("provider_session_id", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_ai_conversations_user_id", "ai_conversations", ["user_id"])
    op.create_table(
        "ai_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("conversation_id", sa.Integer(),
                  sa.ForeignKey("ai_conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("tools", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_ai_messages_conversation_id", "ai_messages", ["conversation_id"])
    op.create_table(
        "ai_pending_actions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("conversation_id", sa.Integer(),
                  sa.ForeignKey("ai_conversations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("tool", sa.String(60), nullable=False),
        sa.Column("input", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("result", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
    )
    for col in ("user_id", "conversation_id", "status"):
        op.create_index(f"ix_ai_pending_actions_{col}", "ai_pending_actions", [col])
    op.create_table(
        "ai_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("conversation_id", sa.Integer(),
                  sa.ForeignKey("ai_conversations.id", ondelete="CASCADE"), nullable=True),
        sa.Column("label", sa.String(100), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_ai_tokens_token_hash", "ai_tokens", ["token_hash"], unique=True)
    op.create_index("ix_ai_tokens_user_id", "ai_tokens", ["user_id"])
    op.create_table(
        "ai_embeddings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("entity_type", sa.String(30), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("text_hash", sa.String(64), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("vector", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("entity_type", "entity_id", "model"),
    )
    op.create_index("ix_ai_embeddings_entity_type", "ai_embeddings", ["entity_type"])
    with op.batch_alter_table("inventory_allocations") as batch:
        batch.add_column(sa.Column("event_team_id", sa.Integer(), nullable=True))
        batch.create_index("ix_inventory_allocations_event_team_id", ["event_team_id"])
        batch.create_foreign_key("fk_inventory_allocations_event_team_id", "event_teams",
                                 ["event_team_id"], ["id"], ondelete="SET NULL")
    with op.batch_alter_table("inventory_items") as batch:
        batch.add_column(sa.Column("aliases", sa.Text(), nullable=False, server_default=""))
    _grant(True)


def downgrade() -> None:
    _grant(False)
    with op.batch_alter_table("inventory_items") as batch:
        batch.drop_column("aliases")
    with op.batch_alter_table("inventory_allocations") as batch:
        batch.drop_constraint("fk_inventory_allocations_event_team_id", type_="foreignkey")
        batch.drop_index("ix_inventory_allocations_event_team_id")
        batch.drop_column("event_team_id")
    for table in ("ai_embeddings", "ai_tokens", "ai_pending_actions", "ai_messages", "ai_conversations"):
        op.drop_table(table)
