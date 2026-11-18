"""Career Copilot: conversations, messages, long-term memories.

Revision ID: 0015_copilot
Revises: 0014_phase2_traceability
Create Date: 2026-11-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0015_copilot"
down_revision: str | None = "0014_phase2_traceability"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "copilot_conversations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(120), nullable=False, server_default="New conversation"),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("summarized_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_copilot_conversations_user_updated",
        "copilot_conversations",
        ["user_id", "updated_at"],
    )

    op.create_table(
        "copilot_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("copilot_conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("tool_calls", postgresql.JSONB(), nullable=True),
        sa.Column("tool_call_id", sa.String(80), nullable=True),
        sa.Column("name", sa.String(80), nullable=True),
        sa.Column("meta", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_copilot_messages_conv_created",
        "copilot_messages",
        ["conversation_id", "created_at"],
    )

    op.create_table(
        "copilot_memories",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(20), nullable=False, server_default="fact"),
        sa.Column("content", sa.String(400), nullable=False),
        sa.Column("source", sa.String(20), nullable=False, server_default="chat"),
        sa.Column("embedding", Vector(768), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_copilot_memories_user", "copilot_memories", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_copilot_memories_user", table_name="copilot_memories")
    op.drop_table("copilot_memories")
    op.drop_index("ix_copilot_messages_conv_created", table_name="copilot_messages")
    op.drop_table("copilot_messages")
    op.drop_index("ix_copilot_conversations_user_updated", table_name="copilot_conversations")
    op.drop_table("copilot_conversations")
