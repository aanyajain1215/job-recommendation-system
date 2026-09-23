"""Career paths, path steps, learning resources.

Revision ID: 0010_paths_and_resources
Revises: 0009_rec_and_feedback
Create Date: 2026-09-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010_paths_and_resources"
down_revision: str | None = "0009_rec_and_feedback"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. career_paths — role → target family with status (plan §7)
    op.create_table(
        "career_paths",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("profile_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("from_family_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("to_family_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("summary", postgresql.JSONB(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("ACTIVE", "COMPLETED", "ABANDONED", name="path_status"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
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
            ["from_family_id"],
            ["job_families.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["to_family_id"],
            ["job_families.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "profile_id",
            "from_family_id",
            "to_family_id",
            name="uq_career_path_profile_route",
        ),
    )
    op.create_index("ix_career_paths_profile_id", "career_paths", ["profile_id"], unique=False)
    op.create_index("ix_career_paths_to_family_id", "career_paths", ["to_family_id"], unique=False)

    # 2. career_path_steps — ordered roadmap with rationale + resources (plan §7)
    op.create_table(
        "career_path_steps",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("path_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum("SKILL", "PROJECT", "CERT", name="path_step_kind"),
            nullable=False,
        ),
        sa.Column("skill_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("rationale", postgresql.JSONB(), nullable=True),
        sa.Column("resources", postgresql.JSONB(), nullable=True),
        sa.Column("est_hours", sa.Float(), nullable=False),
        sa.Column("done_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["path_id"],
            ["career_paths.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["skill_id"],
            ["skills.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("path_id", "seq", name="uq_career_path_step_seq"),
    )
    op.create_index("ix_career_path_steps_path_id", "career_path_steps", ["path_id"], unique=False)
    op.create_index("ix_career_path_steps_skill_id", "career_path_steps", ["skill_id"], unique=False)

    # 3. learning_resources — approved resources per skill (plan §7)
    op.create_table(
        "learning_resources",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("skill_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("url", sa.String(length=500), nullable=True),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("level", sa.String(length=30), nullable=True),
        sa.Column("hours", sa.Float(), nullable=True),
        sa.Column("quality_score", sa.Float(), nullable=False),
        sa.Column("approved", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["skill_id"],
            ["skills.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_learning_resources_skill_id", "learning_resources", ["skill_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_learning_resources_skill_id", table_name="learning_resources")
    op.drop_table("learning_resources")
    op.drop_index("ix_career_path_steps_skill_id", table_name="career_path_steps")
    op.drop_index("ix_career_path_steps_path_id", table_name="career_path_steps")
    op.drop_table("career_path_steps")
    op.drop_index("ix_career_paths_to_family_id", table_name="career_paths")
    op.drop_index("ix_career_paths_profile_id", table_name="career_paths")
    op.drop_table("career_paths")
    sa.Enum(name="path_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="path_step_kind").drop(op.get_bind(), checkfirst=True)
