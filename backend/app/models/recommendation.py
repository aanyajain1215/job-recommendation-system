from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Float, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base

if TYPE_CHECKING:
    from app.models.job import Job
    from app.models.profile import Profile


class Recommendation(Base):
    """Persisted recommendation with the full response snapshot (plan §3, §4)."""

    __tablename__ = "recommendations"
    __table_args__ = (
        Index("ix_recommendations_profile_served", "profile_id", "served_at"),
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
