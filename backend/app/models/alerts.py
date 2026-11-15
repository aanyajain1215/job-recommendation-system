"""Saved-job alerts, digests, and in-app notifications.

The alert feature is seeded by the jobs a seeker has saved
(``applications.status = 'saved'``), not by their profile.  A background
worker finds newly published jobs that look like those saved jobs, records
one digest per run, and fans the matches out to in-app notifications and an
optional email digest.
"""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class JobAlert(Base):
    """Per-user alert preferences (one row per seeker)."""

    __tablename__ = "job_alerts"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_job_alerts_user"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    profile_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )
    email_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )
    # "daily" | "weekly" | "off"
    digest_frequency: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="daily",
        server_default="daily",
    )
    min_score: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=60.0,
        server_default="60",
    )
    max_items: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=5,
        server_default="5",
    )
    last_digest_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        server_onupdate=func.now(),
    )


class JobAlertDigest(Base):
    """One matching/delivery run for a user's alert settings."""

    __tablename__ = "job_alert_digests"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    alert_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("job_alerts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # "sent" | "empty" | "failed"
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="sent",
        server_default="sent",
    )
    item_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    # "in_app" | "email" | "both"
    channel: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="in_app",
        server_default="in_app",
    )
    # "not_sent" | "sent" | "failed" | "disabled"
    email_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="not_sent",
        server_default="not_sent",
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    window_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    window_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    )
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class JobAlertItem(Base):
    """A single newly matched job inside a digest.

    ``(user_id, job_id)`` is unique so a job is only ever alerted once per
    user, even if multiple workers or re-runs overlap.
    """

    __tablename__ = "job_alert_items"
    __table_args__ = (
        UniqueConstraint("user_id", "job_id", name="uq_job_alert_items_user_job"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    digest_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("job_alert_digests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    alert_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("job_alerts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    job_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Which saved job seeded this match (nullable if the seed is later deleted)
    seed_job_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    score: Mapped[float] = mapped_column(Float, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    )


class Notification(Base):
    """In-app notification (currently produced by the job-alert worker)."""

    __tablename__ = "notifications"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    digest_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("job_alert_digests.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    type: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="job_alert",
        server_default="job_alert",
        index=True,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    link: Mapped[str | None] = mapped_column(String(500), nullable=True)
    data: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    )
