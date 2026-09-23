"""Profile preference columns, job families, job source metadata.

Revision ID: 0006_profile_prefs_and_families
Revises: 0005_unique_application
Create Date: 2026-09-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_profile_prefs_and_families"
down_revision: str | None = "0005_unique_application"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. SAVE action for applications (follows 0004's enum-extension pattern)
    op.execute("ALTER TYPE application_status ADD VALUE IF NOT EXISTS 'SAVED'")

    # 2. work_mode enum — created explicitly because ADD COLUMN alone won't
    work_mode = sa.Enum("REMOTE", "HYBRID", "ONSITE", name="work_mode")
    work_mode.create(op.get_bind(), checkfirst=True)

    # 3. job_families — canonical career roles for discovery + path targeting
    op.create_table(
        "job_families",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("parent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("core_skills", postgresql.JSONB(), nullable=True),
        sa.Column("keywords", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["job_families.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_job_families_name"),
    )
    op.create_index("ix_job_families_name", "job_families", ["name"], unique=False)

    # 4. profiles — preference columns (plan §2, §9, §18)
    op.add_column("profiles", sa.Column("expected_salary_min", sa.Integer(), nullable=True))
    op.add_column("profiles", sa.Column("expected_salary_max", sa.Integer(), nullable=True))
    op.add_column(
        "profiles",
        sa.Column("expected_salary_currency", sa.String(length=10), server_default="USD", nullable=False),
    )
    op.add_column("profiles", sa.Column("target_job_family_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("profiles", sa.Column("preferred_work_mode", work_mode, nullable=True))
    op.add_column("profiles", sa.Column("career_interests", postgresql.JSONB(), nullable=True))
    op.add_column(
        "profiles",
        sa.Column("preferred_locations", postgresql.ARRAY(sa.String(length=150)), nullable=True),
    )
    op.create_index("ix_profiles_target_job_family_id", "profiles", ["target_job_family_id"], unique=False)
    op.create_foreign_key(
        "fk_profiles_target_job_family_id",
        "profiles",
        "job_families",
        ["target_job_family_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # 5. companies — industry / headcount (plan §10 discovery filters)
    op.add_column("companies", sa.Column("industry", sa.String(length=100), nullable=True))
    op.add_column("companies", sa.Column("company_size", sa.String(length=50), nullable=True))
    op.create_index("ix_companies_industry", "companies", ["industry"], unique=False)

    # 6. jobs — family assignment + external source tracking (plan §3 corpus)
    op.add_column("jobs", sa.Column("family_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("jobs", sa.Column("source", sa.String(length=30), server_default="native", nullable=False))
    op.add_column("jobs", sa.Column("external_id", sa.String(length=120), nullable=True))
    op.add_column("jobs", sa.Column("external_url", sa.String(length=500), nullable=True))
    op.create_index("ix_jobs_family_id", "jobs", ["family_id"], unique=False)
    op.create_index("ix_jobs_source", "jobs", ["source"], unique=False)
    op.create_foreign_key(
        "fk_jobs_family_id",
        "jobs",
        "job_families",
        ["family_id"],
        ["id"],
        ondelete="SET NULL",
    )
    # NULL external_id allowed repeatedly for native postings
    op.create_unique_constraint("uq_jobs_source_external_id", "jobs", ["source", "external_id"])


def downgrade() -> None:
    op.drop_constraint("uq_jobs_source_external_id", "jobs", type_="unique")
    op.drop_constraint("fk_jobs_family_id", "jobs", type_="foreignkey")
    op.drop_index("ix_jobs_source", table_name="jobs")
    op.drop_index("ix_jobs_family_id", table_name="jobs")
    op.drop_column("jobs", "external_url")
    op.drop_column("jobs", "external_id")
    op.drop_column("jobs", "source")
    op.drop_column("jobs", "family_id")

    op.drop_index("ix_companies_industry", table_name="companies")
    op.drop_column("companies", "company_size")
    op.drop_column("companies", "industry")

    op.drop_constraint("fk_profiles_target_job_family_id", "profiles", type_="foreignkey")
    op.drop_index("ix_profiles_target_job_family_id", table_name="profiles")
    op.drop_column("profiles", "preferred_locations")
    op.drop_column("profiles", "career_interests")
    op.drop_column("profiles", "preferred_work_mode")
    op.drop_column("profiles", "target_job_family_id")
    op.drop_column("profiles", "expected_salary_currency")
    op.drop_column("profiles", "expected_salary_max")
    op.drop_column("profiles", "expected_salary_min")

    op.drop_index("ix_job_families_name", table_name="job_families")
    op.drop_table("job_families")
    sa.Enum(name="work_mode").drop(op.get_bind(), checkfirst=True)
    # NOTE: application_status 'SAVED' cannot be removed — PostgreSQL limitation
