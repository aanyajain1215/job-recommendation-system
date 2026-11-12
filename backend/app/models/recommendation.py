from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum as SQLEnum, Float, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.enums import RecommendationEventType

if TYPE_CHECKING:
    from app.models.feedback import Feedback
    from app.models.job import Job
    from app.models.profile import Profile


class Recommendation(Base):
    """Persisted recommendation with the full response snapshot (plan §3, §4)."""

    __tablename__ = "recommendations"
    __table_args__ = (
        Index("ix_recommendations_profile_served", "profile_id", "served_at"),
        UniqueConstraint("id", "profile_id", "job_id", name="uq_recommendations_id_profile_job"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    profile_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    job_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Full response snapshot incl. component breakdown + explanation contract
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    # "cold_start" | "content_based" | "collaborative" | ...
    strategy: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="content_based",
    )
    model_version: Mapped[str | None] = mapped_column(
        String(40),
        nullable=True,
    )
    # Exploration propensity for inverse-propensity-corrected feedback (§18)
    propensity: Mapped[float | None] = mapped_column(Float, nullable=True)
    served_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # Relationships
    profile: Mapped["Profile"] = relationship("Profile")
    job: Mapped["Job"] = relationship("Job")
    events: Mapped[list["RecommendationEvent"]] = relationship(
        "RecommendationEvent",
        back_populates="recommendation",
        cascade="all, delete-orphan",
    )
    feedback_entries: Mapped[list["Feedback"]] = relationship(
        "Feedback",
        back_populates="recommendation",
        overlaps="feedback_entries,job,profile",
    )


class RecommendationEvent(Base):
    """Lifecycle events for recommendations (generated, served, impression, clicked, etc.)."""

    __tablename__ = "recommendation_events"
    __table_args__ = (
        UniqueConstraint("recommendation_id", "event_type", name="uq_rec_event_rec_type"),
        Index("ix_rec_events_rec_occurred", "recommendation_id", "occurred_at"),
        Index("ix_rec_events_profile_occurred", "profile_id", "occurred_at"),
        Index("ix_rec_events_type_occurred", "event_type", "occurred_at"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    recommendation_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("recommendations.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    profile_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_type: Mapped[RecommendationEventType] = mapped_column(
        SQLEnum(
            RecommendationEventType,
            name="recommendation_event_type",
            native_enum=True,
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        index=True,
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    request_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
    rank: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    metadata_: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata",
        JSONB,
        nullable=True,
    )

    # Relationships
    recommendation: Mapped["Recommendation | None"] = relationship(
        "Recommendation",
        back_populates="events",
    )
    profile: Mapped["Profile"] = relationship("Profile")


class SkillGap(Base):
    """Detected gap classes between a profile and a job (plan §8)."""

    __tablename__ = "skill_gaps"
    __table_args__ = (
        Index("ix_skill_gaps_profile_job_filled", "profile_id", "job_id", "filled_at"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    profile_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    job_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Classes: [{skill, status, evidence}]
    classes: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    filled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # Relationships
    profile: Mapped["Profile"] = relationship("Profile")
    job: Mapped["Job"] = relationship("Job")
