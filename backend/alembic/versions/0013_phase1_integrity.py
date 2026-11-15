"""Phase 1: Core data integrity, profile data, and embedding safety.

Revision ID: 0013_phase1_integrity
Revises: 0013_m0_bge768_embeddings
Create Date: 2026-11-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_phase1_integrity"
down_revision: str | None = "0013_m0_bge768_embeddings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # -----------------------------------------------------------------------
    # Phase 1.1: Application User/Profile Ownership
    # -----------------------------------------------------------------------
    # 1. Unique constraint on profiles(id, user_id)
    op.create_unique_constraint(
        "uq_profiles_id_user_id",
        "profiles",
        ["id", "user_id"],
    )

    # 2. Composite foreign key from applications(profile_id, user_id) to profiles(id, user_id)
    op.create_foreign_key(
        "fk_applications_profile_user",
        "applications",
        "profiles",
        ["profile_id", "user_id"],
        ["id", "user_id"],
        ondelete="CASCADE",
    )

    # -----------------------------------------------------------------------
    # Phase 1.3: Embedding Provenance Metadata
    # -----------------------------------------------------------------------
    for table_name in ("profiles", "jobs", "skills"):
        op.add_column(
            table_name,
            sa.Column("embedding_backend", sa.String(length=30), nullable=True),
        )
        op.add_column(
            table_name,
            sa.Column("embedding_model", sa.String(length=100), nullable=True),
        )
        op.add_column(
            table_name,
            sa.Column("embedding_version", sa.String(length=30), nullable=True),
        )
        op.add_column(
            table_name,
            sa.Column("embedding_dimension", sa.Integer(), nullable=True),
        )
        op.add_column(
            table_name,
            sa.Column("embedding_content_hash", sa.String(length=64), nullable=True),
        )

    # -----------------------------------------------------------------------
    # Phase 1.4: Skill Alias Normalization and Graph Validation
    # -----------------------------------------------------------------------
    # 1. Normalized alias column on skill_aliases
    op.add_column(
        "skill_aliases",
        sa.Column("normalized_alias", sa.String(length=150), nullable=True),
    )
    # Populate existing rows with canonical whitespace & lowercase normalization
    op.execute(
        "UPDATE skill_aliases "
        "SET normalized_alias = lower(regexp_replace(trim(alias), E'\\\\s+', ' ', 'g')) "
        "WHERE normalized_alias IS NULL"
    )
    op.alter_column("skill_aliases", "normalized_alias", nullable=False)
    op.create_unique_constraint(
        "uq_skill_aliases_normalized_alias",
        "skill_aliases",
        ["normalized_alias"],
    )
    op.create_index(
        "ix_skill_aliases_normalized_alias",
        "skill_aliases",
        ["normalized_alias"],
        unique=False,
    )

    # 2. Graph constraints on skill_edges
    op.create_check_constraint(
        "ck_skill_edges_no_self_loop",
        "skill_edges",
        "from_skill_id != to_skill_id",
    )
    op.create_check_constraint(
        "ck_skill_edges_weight_range",
        "skill_edges",
        "weight >= 0.0 AND weight <= 10.0",
    )

    # -----------------------------------------------------------------------
    # Phase 1.2: Profile Source of Truth Safe Backfill
    # -----------------------------------------------------------------------
    # Idempotently migrate existing JSONB education into structured education rows
    op.execute("""
        INSERT INTO education (id, profile_id, degree, institution, field_of_study, grad_year, is_primary, created_at)
        SELECT
            gen_random_uuid(),
            p.id,
            COALESCE(elem->>'degree', elem->>'degree_name'),
            COALESCE(elem->>'institution', elem->>'school'),
            COALESCE(elem->>'field_of_study', elem->>'major'),
            CASE WHEN (elem->>'grad_year') ~ '^[0-9]+$' THEN (elem->>'grad_year')::int ELSE NULL END,
            COALESCE((elem->>'is_primary')::boolean, false),
            now()
        FROM profiles p,
        jsonb_array_elements(p.education) elem
        WHERE p.education IS NOT NULL
          AND jsonb_typeof(p.education) = 'array'
          AND NOT EXISTS (
              SELECT 1 FROM education e
              WHERE e.profile_id = p.id
                AND lower(trim(COALESCE(e.degree, ''))) = lower(trim(COALESCE(elem->>'degree', elem->>'degree_name', '')))
                AND lower(trim(COALESCE(e.institution, ''))) = lower(trim(COALESCE(elem->>'institution', elem->>'school', '')))
          );
    """)

    # Idempotently migrate existing JSONB work_experience into structured experience rows
    op.execute("""
        INSERT INTO experience (id, profile_id, title, company, location, start_date, end_date, current, description, skills_used, created_at)
        SELECT
            gen_random_uuid(),
            p.id,
            COALESCE(elem->>'title', elem->>'role', elem->>'position', 'Position'),
            COALESCE(elem->>'company', elem->>'employer', elem->>'organization'),
            elem->>'location',
            elem->>'start_date',
            elem->>'end_date',
            COALESCE((elem->>'current')::boolean, false),
            elem->>'description',
            CASE WHEN elem->'skills_used' IS NOT NULL AND jsonb_typeof(elem->'skills_used') = 'array' THEN elem->'skills_used' ELSE NULL END,
            now()
        FROM profiles p,
        jsonb_array_elements(p.work_experience) elem
        WHERE p.work_experience IS NOT NULL
          AND jsonb_typeof(p.work_experience) = 'array'
          AND NOT EXISTS (
              SELECT 1 FROM experience exp
              WHERE exp.profile_id = p.id
                AND lower(trim(COALESCE(exp.title, ''))) = lower(trim(COALESCE(elem->>'title', elem->>'role', elem->>'position', '')))
                AND lower(trim(COALESCE(exp.company, ''))) = lower(trim(COALESCE(elem->>'company', elem->>'employer', elem->>'organization', '')))
          );
    """)


def downgrade() -> None:
    # Phase 1.4: Remove graph constraints and normalized alias
    op.drop_constraint("ck_skill_edges_weight_range", "skill_edges", type_="check")
    op.drop_constraint("ck_skill_edges_no_self_loop", "skill_edges", type_="check")

    op.drop_index("ix_skill_aliases_normalized_alias", table_name="skill_aliases")
    op.drop_constraint("uq_skill_aliases_normalized_alias", "skill_aliases", type_="unique")
    op.drop_column("skill_aliases", "normalized_alias")

    # Phase 1.3: Remove embedding provenance columns
    for table_name in ("skills", "jobs", "profiles"):
        op.drop_column(table_name, "embedding_content_hash")
        op.drop_column(table_name, "embedding_dimension")
        op.drop_column(table_name, "embedding_version")
        op.drop_column(table_name, "embedding_model")
        op.drop_column(table_name, "embedding_backend")

    # Phase 1.1: Remove composite FK and unique constraint
    op.drop_constraint("fk_applications_profile_user", "applications", type_="foreignkey")
    op.drop_constraint("uq_profiles_id_user_id", "profiles", type_="unique")

