"""Structured profile tables: resumes, education, experience, projects, certifications.

Revision ID: 0007_structured_profile_tables
Revises: 0006_profile_prefs_and_families
Create Date: 2026-09-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_structured_profile_tables"
down_revision: str | None = "0006_profile_prefs_and_families"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. resumes — versioned uploads with extraction evidence (plan §3, §20)
    op.create_table(
        "resumes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("profile_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("file_path", sa.String(length=500), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=True),
        sa.Column("parse_status", sa.String(length=20), nullable=False),
        sa.Column("parser_used", sa.String(length=20), nullable=True),
        sa.Column("extracted", postgresql.JSONB(), nullable=True),
        sa.Column("evidence", postgresql.JSONB(), nullable=True),
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
    op.create_index("ix_resumes_profile_id", "resumes", ["profile_id"], unique=False)

    # 2. education
    op.create_table(
        "education",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("profile_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("degree", sa.String(length=200), nullable=True),
        sa.Column("institution", sa.String(length=200), nullable=True),
        sa.Column("field_of_study", sa.String(length=200), nullable=True),
        sa.Column("grad_year", sa.Integer(), nullable=True),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
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
    op.create_index("ix_education_profile_id", "education", ["profile_id"], unique=False)

    # 3. experience
    op.create_table(
        "experience",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("profile_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("company", sa.String(length=200), nullable=True),
        sa.Column("location", sa.String(length=150), nullable=True),
        sa.Column("start_date", sa.String(length=30), nullable=True),
        sa.Column("end_date", sa.String(length=30), nullable=True),
        sa.Column("current", sa.Boolean(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("skills_used", postgresql.JSONB(), nullable=True),
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
    op.create_index("ix_experience_profile_id", "experience", ["profile_id"], unique=False)

    # 4. projects — detected_skills filled by P8 project-mapping (plan §19)
    op.create_table(
        "projects",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("profile_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("links", postgresql.JSONB(), nullable=True),
        sa.Column(
            "detected_skills",
            postgresql.JSONB(),
            server_default=sa.text("'[]'"),
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
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_projects_profile_id", "projects", ["profile_id"], unique=False)

    # 5. certifications
    op.create_table(
        "certifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("profile_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("issuer", sa.String(length=150), nullable=True),
        sa.Column("issued_at", sa.String(length=30), nullable=True),
        sa.Column("expires_at", sa.String(length=30), nullable=True),
        sa.Column("credential_url", sa.String(length=500), nullable=True),
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
    op.create_index("ix_certifications_profile_id", "certifications", ["profile_id"], unique=False)

    # 6. applications — link to the resume version submitted with (plan §3)
    op.add_column(
        "applications",
        sa.Column("resume_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_applications_resume_id",
        "applications",
        "resumes",
        ["resume_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_applications_resume_id", "applications", type_="foreignkey")
    op.drop_column("applications", "resume_id")

    op.drop_index("ix_certifications_profile_id", table_name="certifications")
    op.drop_table("certifications")
    op.drop_index("ix_projects_profile_id", table_name="projects")
    op.drop_table("projects")
    op.drop_index("ix_experience_profile_id", table_name="experience")
    op.drop_table("experience")
    op.drop_index("ix_education_profile_id", table_name="education")
    op.drop_table("education")
    op.drop_index("ix_resumes_profile_id", table_name="resumes")
    op.drop_table("resumes")
