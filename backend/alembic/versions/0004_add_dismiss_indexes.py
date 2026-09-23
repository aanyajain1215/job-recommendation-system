"""Add DISMISS to interaction_type enum and composite indexes on interactions table."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_add_dismiss_indexes"
down_revision: str | None = "0003_jobs_full_text_search"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Add DISMISS value to PostgreSQL native enum interaction_type
    op.execute("ALTER TYPE interaction_type ADD VALUE IF NOT EXISTS 'DISMISS'")

    # 2. Add composite indexes for collaborative filtering and analytics
    op.create_index(
        "ix_interactions_user_event",
        "interactions",
        ["user_id", "event_type", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_interactions_job_event",
        "interactions",
        ["job_id", "event_type", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_interactions_job_event", table_name="interactions")
    op.drop_index("ix_interactions_user_event", table_name="interactions")
