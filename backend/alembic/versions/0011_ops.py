"""Ops tables: model registry, LLM usage log, system config.

Revision ID: 0011_ops
Revises: 0010_paths_and_resources
Create Date: 2026-09-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011_ops"
down_revision: str | None = "0010_paths_and_resources"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. model_registry — trained artifacts + metrics (plan §17)
    op.create_table(
        "model_registry",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column("version", sa.String(length=40), nullable=False),
        sa.Column("artifact_path", sa.String(length=500), nullable=False),
        sa.Column("metrics", postgresql.JSONB(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("trained_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", "version", name="uq_model_registry_name_version"),
    )
    op.create_index("ix_model_registry_name", "model_registry", ["name"], unique=False)

    # 2. llm_usage — per-call token/latency log for cost guardrails (plan §15)
    op.create_table(
        "llm_usage",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("route", sa.String(length=80), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("model", sa.String(length=80), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("cached", sa.Boolean(), nullable=False),
        sa.Column("flagged", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_llm_usage_route", "llm_usage", ["route"], unique=False)
    op.create_index("ix_llm_usage_created_at", "llm_usage", ["created_at"], unique=False)

    # 3. system_config — runtime-tunable configuration (plan §14)
    op.create_table(
        "system_config",
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("value", postgresql.JSONB(), nullable=True),
        sa.Column("description", sa.String(length=300), nullable=True),
        sa.Column("updated_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("key"),
    )

    # 4. Seed default scoring weights (plan §6 — editable later via admin §14)
    op.execute(
        """
        INSERT INTO system_config (key, value, description, updated_at)
        VALUES (
            'scoring_weights',
            '{"semantic": 0.30, "skill": 0.25, "experience": 0.15, "education": 0.10,
              "project": 0.05, "location": 0.05, "salary": 0.05, "interest": 0.05}'::jsonb,
            'Deterministic recommendation score component weights (plan section 6)',
            now()
        )
        ON CONFLICT (key) DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_table("system_config")
    op.drop_index("ix_llm_usage_created_at", table_name="llm_usage")
    op.drop_index("ix_llm_usage_route", table_name="llm_usage")
    op.drop_table("llm_usage")
    op.drop_index("ix_model_registry_name", table_name="model_registry")
    op.drop_table("model_registry")
