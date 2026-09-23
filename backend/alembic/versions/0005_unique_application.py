"""Add unique index on applications (job_id, user_id) for idempotent submissions.

Revision ID: 0005_unique_application
Revises: 0004_add_dismiss_indexes
Create Date: 2026-09-20
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005_unique_application"
down_revision: str | None = "0004_add_dismiss_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Ensure idempotency index exists at the DB level on (job_id, user_id)
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_applications_job_user_unique ON applications (job_id, user_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_applications_job_user_unique")
