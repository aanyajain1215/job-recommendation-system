"""Add search_vector column, GIN index, and FTS update trigger to jobs table."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_jobs_full_text_search"
down_revision: str | None = "60a53cb7a4cc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Add search_vector column
    op.add_column("jobs", sa.Column("search_vector", postgresql.TSVECTOR(), nullable=True))

    # 2. Create GIN index for fast text retrieval
    op.create_index(
        "ix_jobs_search_vector",
        "jobs",
        ["search_vector"],
        unique=False,
        postgresql_using="gin",
    )

    # 3. Create PL/pgSQL trigger function with weighted fields
    op.execute(
        """
        CREATE OR REPLACE FUNCTION jobs_search_vector_trigger() RETURNS trigger AS $$
        BEGIN
          NEW.search_vector :=
            setweight(to_tsvector('english', coalesce(NEW.title, '')), 'A') ||
            setweight(to_tsvector('english', coalesce(NEW.requirements, '')), 'B') ||
            setweight(to_tsvector('english', coalesce(NEW.description, '')), 'C');
          RETURN NEW;
        END
        $$ LANGUAGE plpgsql;
        """
    )

    # 4. Attach trigger to automatically maintain search_vector on insert/update
    op.execute(
        """
        DROP TRIGGER IF EXISTS tsvectorupdate_jobs ON jobs;
        CREATE TRIGGER tsvectorupdate_jobs BEFORE INSERT OR UPDATE
        ON jobs FOR EACH ROW EXECUTE FUNCTION jobs_search_vector_trigger();
        """
    )

    # 5. Backfill existing jobs
    op.execute(
        """
        UPDATE jobs SET search_vector =
          setweight(to_tsvector('english', coalesce(title, '')), 'A') ||
          setweight(to_tsvector('english', coalesce(requirements, '')), 'B') ||
          setweight(to_tsvector('english', coalesce(description, '')), 'C');
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS tsvectorupdate_jobs ON jobs;")
    op.execute("DROP FUNCTION IF EXISTS jobs_search_vector_trigger();")
    op.drop_index("ix_jobs_search_vector", table_name="jobs")
    op.drop_column("jobs", "search_vector")
