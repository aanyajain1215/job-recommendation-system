"""Skill graph tables, skill embeddings, profile skill provenance.

Revision ID: 0008_skill_graph
Revises: 0007_structured_profile_tables
Create Date: 2026-09-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0008_skill_graph"
down_revision: str | None = "0007_structured_profile_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. profile_skills provenance — manual vs resume-sourced skills
    profile_skill_source = sa.Enum("MANUAL", "RESUME", name="profile_skill_source")
    profile_skill_source.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "profile_skills",
        sa.Column("source", profile_skill_source, server_default="MANUAL", nullable=False),
    )

    # 2. skills — 384-d embedding for skill2vec/transfer similarity (plan §13)
    op.add_column("skills", sa.Column("embedding", Vector(384), nullable=True))
    op.add_column("skills", sa.Column("embedding_updated_at", sa.DateTime(timezone=True), nullable=True))

    # HNSW cosine indexes power KNN candidate generation (plan §4)
    op.create_index(
        "ix_jobs_embedding_hnsw",
        "jobs",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_index(
        "ix_profiles_embedding_hnsw",
        "profiles",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_index(
        "ix_skills_embedding_hnsw",
        "skills",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )

    # 3. skill_aliases — alias → canonical mapping (plan §20 normalizer)
    op.create_table(
        "skill_aliases",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("alias", sa.String(length=150), nullable=False),
        sa.Column("skill_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
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
        sa.UniqueConstraint("alias", name="uq_skill_alias_alias"),
    )
    op.create_index("ix_skill_aliases_skill_id", "skill_aliases", ["skill_id"], unique=False)

    # 4. skill_edges — prereq | transfer | supersedes graph (plan §5, §8)
    op.create_table(
        "skill_edges",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("from_skill_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("to_skill_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "edge_type",
            sa.Enum("PREREQ", "TRANSFER", "SUPERSEDES", name="skill_edge_type"),
            nullable=False,
        ),
        sa.Column("weight", sa.Float(), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("approved", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["from_skill_id"],
            ["skills.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["to_skill_id"],
            ["skills.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "from_skill_id",
            "to_skill_id",
            "edge_type",
            name="uq_skill_edge",
        ),
    )
    op.create_index("ix_skill_edges_from_skill_id", "skill_edges", ["from_skill_id"], unique=False)
    op.create_index("ix_skill_edges_to_skill_id", "skill_edges", ["to_skill_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_skill_edges_to_skill_id", table_name="skill_edges")
    op.drop_index("ix_skill_edges_from_skill_id", table_name="skill_edges")
    op.drop_table("skill_edges")

    op.drop_index("ix_skill_aliases_skill_id", table_name="skill_aliases")
    op.drop_table("skill_aliases")

    op.drop_index("ix_skills_embedding_hnsw", table_name="skills")
    op.drop_index("ix_profiles_embedding_hnsw", table_name="profiles")
    op.drop_index("ix_jobs_embedding_hnsw", table_name="jobs")
    op.drop_column("skills", "embedding_updated_at")
    op.drop_column("skills", "embedding")

    op.drop_column("profile_skills", "source")
    sa.Enum(name="profile_skill_source").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="skill_edge_type").drop(op.get_bind(), checkfirst=True)
