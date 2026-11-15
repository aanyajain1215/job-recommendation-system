"""Admin monitoring: live activity + trust & safety flags + HIRED status.

Revision ID: 0015_admin_trust
Revises: 0014_phase2_traceability
Create Date: 2026-11-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015_admin_trust"
down_revision: str | None = "0014_phase2_traceability"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Live-usage signal. Nullable so existing rows are untouched; recent
    #    rows get a best-effort backfill from updated_at (older history is not
    #    trustworthy enough to claim as activity).
    op.add_column(
        "users",
        sa.Column("last_active_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_users_last_active_at", "users", ["last_active_at"], unique=False
    )
    op.execute(
        """
        UPDATE users
        SET last_active_at = updated_at
        WHERE last_active_at IS NULL
          AND updated_at >= now() - interval '30 days'
        """
    )

    # 2. A real terminal pipeline stage so "got a job" is measurable rather
    #    than inferred from `offer`. PG 12+ allows ADD VALUE in a transaction
    #    as long as the value is not used in the same transaction.
    op.execute(
        "ALTER TYPE application_status ADD VALUE IF NOT EXISTS 'HIRED'"
    )

    # 3. Trust & safety flag vocabulary.
    flag_target_type = sa.Enum(
        "JOB", "COMPANY", "USER", name="flag_target_type"
    )
    flag_severity = sa.Enum("LOW", "MEDIUM", "HIGH", name="flag_severity")
    flag_status = sa.Enum("OPEN", "RESOLVED", "DISMISSED", name="flag_status")

    # 4. Polymorphic flag queue (job / company / user targets).
    op.create_table(
        "moderation_flags",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_type", flag_target_type, nullable=False),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_label", sa.String(length=255), nullable=True),
        sa.Column("reason", sa.String(length=160), nullable=False),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("severity", flag_severity, nullable=False),
        sa.Column("status", flag_status, nullable=False),
        sa.Column(
            "created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column(
            "resolved_by_user_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["resolved_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_moderation_flags_status_type",
        "moderation_flags",
        ["status", "target_type"],
        unique=False,
    )
    op.create_index(
        "ix_moderation_flags_target",
        "moderation_flags",
        ["target_type", "target_id"],
        unique=False,
    )
    op.create_index(
        "ix_moderation_flags_created_at",
        "moderation_flags",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "ix_moderation_flags_status",
        "moderation_flags",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_moderation_flags_created_by_user_id",
        "moderation_flags",
        ["created_by_user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_moderation_flags_created_by_user_id", table_name="moderation_flags"
    )
    op.drop_index("ix_moderation_flags_status", table_name="moderation_flags")
    op.drop_index("ix_moderation_flags_created_at", table_name="moderation_flags")
    op.drop_index("ix_moderation_flags_target", table_name="moderation_flags")
    op.drop_index(
        "ix_moderation_flags_status_type", table_name="moderation_flags"
    )
    op.drop_table("moderation_flags")

    sa.Enum(name="flag_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="flag_severity").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="flag_target_type").drop(op.get_bind(), checkfirst=True)

    # Postgres cannot remove a value from an enum without rebuilding the type,
    # so HIRED is intentionally left in place on downgrade.

    op.drop_index("ix_users_last_active_at", table_name="users")
    op.drop_column("users", "last_active_at")
