"""Recommendations, skill gaps, feedback, skill affinities, simulations.

Revision ID: 0009_rec_and_feedback
Revises: 0008_skill_graph
Create Date: 2026-09-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009_rec_and_feedback"
down_revision: str | None = "0008_skill_graph"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. recommendations — served feed persisted with full snapshot (plan §3, §4)
    op.create_table(
        "recommendations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("profile_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("strategy", sa.String(length=40), nullable=False),
        sa.Column("model_version", sa.String(length=40), nullable=True),
        sa.Column("propensity", sa.Float(), nullable=True),
        sa.Column(
            "served_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["profiles.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["jobs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_recommendations_profile_id", "recommendations", ["profile_id"], unique=False)
    op.create_index("ix_recommendations_job_id", "recommendations", ["job_id"], unique=False)
    op.create_index(
        "ix_recommendations_profile_served",
        "recommendations",
        ["profile_id", "served_at"],
        unique=False,
    )

    # 2. skill_gaps — gap classification per profile/job pair (plan §8)
    op.create_table(
        "skill_gaps",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("profile_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("classes", postgresql.JSONB(), nullable=False),
        sa.Column(
            "filled_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["profiles.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["jobs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_skill_gaps_profile_id", "skill_gaps", ["profile_id"], unique=False)
    op.create_index("ix_skill_gaps_job_id", "skill_gaps", ["job_id"], unique=False)
    op.create_index(
        "ix_skill_gaps_profile_job_filled",
        "skill_gaps",
        ["profile_id", "job_id", "filled_at"],
        unique=False,
    )

    # 3. feedback — explicit reasons on recommendations (plan §10)
    op.create_table(
        "feedback",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("profile_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "reason",
            sa.Enum(
                "RELEVANT",
                "NOT_RELEVANT",
                "ALREADY_APPLIED",
                "NOT_INTERESTED",
                "TOO_DIFFICULT",
                "LOCATION_ISSUE",
                "SALARY_ISSUE",
                "OTHER",
                name="feedback_reason",
            ),
            nullable=False,
        ),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["profiles.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["jobs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_feedback_profile_id", "feedback", ["profile_id"], unique=False)
    op.create_index("ix_feedback_job_id", "feedback", ["job_id"], unique=False)
    op.create_index("ix_feedback_created_at", "feedback", ["created_at"], unique=False)

    # 4. skill_affinities — learned per-profile skill scores (plan §10)
    op.create_table(
        "skill_affinities",
        sa.Column("profile_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("skill_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("half_life_days", sa.Float(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["profiles.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["skill_id"],
            ["skills.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("profile_id", "skill_id"),
    )

    # 5. simulations — What-If simulator runs (plan §9)
    op.create_table(
        "simulations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("profile_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("mutation", postgresql.JSONB(), nullable=False),
        sa.Column("result_delta", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["profiles.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_simulations_profile_id", "simulations", ["profile_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_simulations_profile_id", table_name="simulations")
    op.drop_table("simulations")
    op.drop_table("skill_affinities")
    op.drop_index("ix_feedback_created_at", table_name="feedback")
    op.drop_index("ix_feedback_job_id", table_name="feedback")
    op.drop_index("ix_feedback_profile_id", table_name="feedback")
    op.drop_table("feedback")
    op.drop_index("ix_skill_gaps_profile_job_filled", table_name="skill_gaps")
    op.drop_index("ix_skill_gaps_job_id", table_name="skill_gaps")
    op.drop_index("ix_skill_gaps_profile_id", table_name="skill_gaps")
    op.drop_table("skill_gaps")
    op.drop_index("ix_recommendations_profile_served", table_name="recommendations")
    op.drop_index("ix_recommendations_job_id", table_name="recommendations")
    op.drop_index("ix_recommendations_profile_id", table_name="recommendations")
    op.drop_table("recommendations")
    sa.Enum(name="feedback_reason").drop(op.get_bind(), checkfirst=True)
