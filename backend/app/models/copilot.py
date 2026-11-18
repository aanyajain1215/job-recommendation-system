"""Career Copilot: conversations, messages and long-term user memory.

Two memory tiers back the agent:

* **Short-term** — ``copilot_messages`` replayed each turn (bounded window),
  with older turns folded into ``copilot_conversations.summary``.
* **Long-term** — ``copilot_memories``: durable facts about the seeker
  (preferences, dealbreakers, goals) extracted from chat or saved via the
  ``remember`` tool, embedded (768-d) so the most relevant ones are recalled
  per turn by cosine similarity.  Users can list and delete them.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base

MEMORY_KINDS = ("preference", "dealbreaker", "goal", "fact")


class CopilotConversation(Base):
    __tablename__ = "copilot_conversations"
    __table_args__ = (Index("ix_copilot_conversations_user_updated", "user_id", "updated_at"),)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(120), nullable=False, default="New conversation")
    # rolling summary of messages that fell out of the replay window
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    summarized_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    messages: Mapped[list["CopilotMessage"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="CopilotMessage.created_at",
    )


class CopilotMessage(Base):
    __tablename__ = "copilot_messages"
    __table_args__ = (Index("ix_copilot_messages_conv_created", "conversation_id", "created_at"),)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    conversation_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("copilot_conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    # user | assistant | tool
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # assistant: [{id, name, arguments}] requested; tool: the call it answers
    tool_calls: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    tool_call_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    # UI payload: job cards, gap reports, trace, mode
    meta: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    conversation: Mapped[CopilotConversation] = relationship(back_populates="messages")


class CopilotMemory(Base):
    __tablename__ = "copilot_memories"
    __table_args__ = (Index("ix_copilot_memories_user", "user_id"),)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="fact")
    content: Mapped[str] = mapped_column(String(400), nullable=False)
    # "chat" (auto-extracted) | "tool" (agent called remember) | "user"
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="chat")
    embedding: Mapped[list[float] | None] = mapped_column(Vector(768), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
