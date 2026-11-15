"""M0 upgrade: BGE bi-encoder embeddings (768-d) + reset for re-embedding.

Changes embedding vector dimensions from 384 -> 768 for profiles/jobs/skills to
support BAAI/bge-base-en-v1.5 domain-fine-tuned bi-encoder. Existing vectors
are cleared because dimensionality changes; run backfill/re-embedding after.

Revision ID: 0013_m0_bge768_embeddings
Revises: 0012_adzuna_currency_backfill
Create Date: 2026-11-15
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0013_m0_bge768_embeddings"
down_revision: str | None = "0012_adzuna_currency_backfill"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _drop_embedding_indexes() -> None:
    # Drop any vector indexes that may depend on old dimension (names may vary).
    for name in (
        "ix_jobs_embedding_hnsw",
        "ix_profiles_embedding_hnsw",
        "ix_skills_embedding_hnsw",
    ):
        op.execute(f"DROP INDEX IF EXISTS {name}")


def upgrade() -> None:
    _drop_embedding_indexes()
    # Clear incompatible vectors/timestamps before type change.
    for table in ("profiles", "jobs", "skills"):
        op.execute(f"UPDATE {table} SET embedding = NULL, embedding_updated_at = NULL")
        op.execute(f"ALTER TABLE {table} ALTER COLUMN embedding TYPE vector(768)")
    # Recreate HNSW indexes for cosine distance (pgvector). Safe if extension supports it.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_jobs_embedding_hnsw ON jobs USING hnsw (embedding vector_cosine_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_profiles_embedding_hnsw ON profiles USING hnsw (embedding vector_cosine_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_skills_embedding_hnsw ON skills USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    _drop_embedding_indexes()
    for table in ("profiles", "jobs", "skills"):
        op.execute(f"UPDATE {table} SET embedding = NULL, embedding_updated_at = NULL")
        op.execute(f"ALTER TABLE {table} ALTER COLUMN embedding TYPE vector(384)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_jobs_embedding_hnsw ON jobs USING hnsw (embedding vector_cosine_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_profiles_embedding_hnsw ON profiles USING hnsw (embedding vector_cosine_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_skills_embedding_hnsw ON skills USING hnsw (embedding vector_cosine_ops)"
    )
