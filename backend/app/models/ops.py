from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class ModelRegistry(Base):
    """Registry of trained model artifacts (plan §17)."""

    __tablename__ = "model_registry"
    __table_args__ = (
        UniqueConstraint("name", "version", name="uq_model_registry_name_version"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    # e.g. "skill2vec", "ranklet", "isotonic-calibrator"
    name: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(40), nullable=False)
    artifact_path: Mapped[str] = mapped_column(String(500), nullable=False)
    metrics: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    trained_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class LlmUsage(Base):
    """Per-call LLM usage log for cost/quota guardrails (plan §15)."""

    __tablename__ = "llm_usage"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    route: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    model: Mapped[str] = mapped_column(String(80), nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cached: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    flagged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    )


class SystemConfig(Base):
    """Single store for runtime-tunable configuration (plan §14)."""

    __tablename__ = "system_config"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    description: Mapped[str | None] = mapped_column(String(300), nullable=True)
    updated_by_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        server_onupdate=func.now(),
    )
