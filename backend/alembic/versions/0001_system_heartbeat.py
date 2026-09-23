"""Create system_heartbeat table and seed the foundation row."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_system_heartbeat"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

HEARTBEAT_ID = "00000000-0000-4000-8000-000000000001"


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')

    op.create_table(
        "system_heartbeat",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("message", sa.String(length=255), nullable=False),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.execute(
        sa.text(
            f"""
            INSERT INTO system_heartbeat (id, message)
            VALUES ('{HEARTBEAT_ID}', 'Postgres is reachable from JobRec API')
            """
        )
    )


def downgrade() -> None:
    op.drop_table("system_heartbeat")
    op.execute("DROP EXTENSION IF EXISTS vector")
