"""Saved-job alerts: alert settings, digests, digest items, notifications.

Revision ID: 0013_job_alerts
Revises: 0012_adzuna_currency_backfill
Create Date: 2026-10-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013_job_alerts"
down_revision: str | None = "0012_adzuna_currency_backfill"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. job_alerts — one row of per-user preferences
    op.create_table(
        "job_alerts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("profile_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "enabled",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "email_enabled",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "digest_frequency",
            sa.String(length=20),
            server_default="daily",
            nullable=False,
        ),
        sa.Column(
            "min_score",
            sa.Float(),
            server_default=sa.text("60"),
            nullable=False,
        ),
        sa.Column(
            "max_items",
            sa.Integer(),
            server_default=sa.text("5"),
            nullable=False,
        ),
        sa.Column("last_digest_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["profile_id"], ["profiles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_job_alerts_user"),
    )
    op.create_index("ix_job_alerts_user_id", "job_alerts", ["user_id"], unique=False)
    op.create_index(
        "ix_job_alerts_profile_id", "job_alerts", ["profile_id"], unique=False
    )
    op.create_index(
        "ix_job_alerts_last_digest_at",
        "job_alerts",
        ["last_digest_at"],
        unique=False,
    )

    # 2. job_alert_digests — one delivery run per user
    op.create_table(
        "job_alert_digests",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("alert_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default="sent",
            nullable=False,
        ),
        sa.Column(
            "item_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "channel",
            sa.String(length=20),
            server_default="in_app",
            nullable=False,
        ),
        sa.Column(
            "email_status",
            sa.String(length=20),
            server_default="not_sent",
            nullable=False,
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["alert_id"], ["job_alerts.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_job_alert_digests_alert_id",
        "job_alert_digests",
        ["alert_id"],
        unique=False,
    )
    op.create_index(
        "ix_job_alert_digests_user_id",
        "job_alert_digests",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_job_alert_digests_created_at",
        "job_alert_digests",
        ["created_at"],
        unique=False,
    )

    # 3. job_alert_items — matched jobs; unique per (user, job)
    op.create_table(
        "job_alert_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("digest_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("alert_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("seed_job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["digest_id"], ["job_alert_digests.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["alert_id"], ["job_alerts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["seed_job_id"], ["jobs.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "job_id", name="uq_job_alert_items_user_job"
        ),
    )
    op.create_index(
        "ix_job_alert_items_digest_id",
        "job_alert_items",
        ["digest_id"],
        unique=False,
    )
    op.create_index(
        "ix_job_alert_items_alert_id",
        "job_alert_items",
        ["alert_id"],
        unique=False,
    )
    op.create_index(
        "ix_job_alert_items_user_id",
        "job_alert_items",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_job_alert_items_job_id",
        "job_alert_items",
        ["job_id"],
        unique=False,
    )
    op.create_index(
        "ix_job_alert_items_seed_job_id",
        "job_alert_items",
        ["seed_job_id"],
        unique=False,
    )
    op.create_index(
        "ix_job_alert_items_created_at",
        "job_alert_items",
        ["created_at"],
        unique=False,
    )

    # 4. notifications — in-app inbox
    op.create_table(
        "notifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("digest_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "type",
            sa.String(length=40),
            server_default="job_alert",
            nullable=False,
        ),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("link", sa.String(length=500), nullable=True),
        sa.Column("data", postgresql.JSONB(), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["digest_id"], ["job_alert_digests.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_notifications_user_id",
        "notifications",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_notifications_digest_id",
        "notifications",
        ["digest_id"],
        unique=False,
    )
    op.create_index(
        "ix_notifications_type",
        "notifications",
        ["type"],
        unique=False,
    )
    op.create_index(
        "ix_notifications_read_at",
        "notifications",
        ["read_at"],
        unique=False,
    )
    op.create_index(
        "ix_notifications_created_at",
        "notifications",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_notifications_created_at", table_name="notifications")
    op.drop_index("ix_notifications_read_at", table_name="notifications")
    op.drop_index("ix_notifications_type", table_name="notifications")
    op.drop_index("ix_notifications_digest_id", table_name="notifications")
    op.drop_index("ix_notifications_user_id", table_name="notifications")
    op.drop_table("notifications")

    op.drop_index("ix_job_alert_items_created_at", table_name="job_alert_items")
    op.drop_index("ix_job_alert_items_seed_job_id", table_name="job_alert_items")
    op.drop_index("ix_job_alert_items_job_id", table_name="job_alert_items")
    op.drop_index("ix_job_alert_items_user_id", table_name="job_alert_items")
    op.drop_index("ix_job_alert_items_alert_id", table_name="job_alert_items")
    op.drop_index("ix_job_alert_items_digest_id", table_name="job_alert_items")
    op.drop_table("job_alert_items")

    op.drop_index(
        "ix_job_alert_digests_created_at", table_name="job_alert_digests"
    )
    op.drop_index("ix_job_alert_digests_user_id", table_name="job_alert_digests")
    op.drop_index("ix_job_alert_digests_alert_id", table_name="job_alert_digests")
    op.drop_table("job_alert_digests")

    op.drop_index("ix_job_alerts_last_digest_at", table_name="job_alerts")
    op.drop_index("ix_job_alerts_profile_id", table_name="job_alerts")
    op.drop_index("ix_job_alerts_user_id", table_name="job_alerts")
    op.drop_table("job_alerts")
