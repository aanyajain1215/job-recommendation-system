from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    DateTime,
    Enum as SQLEnum,
    Float,
    ForeignKey,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.enums import FeedbackReason

if TYPE_CHECKING:
    from app.models.job import Job
    from app.models.profile import Profile


class Feedback(Base):
    """Explicit user feedback on a recommendation (plan §10)."""

    __tablename__ = "feedback"

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
    reason: Mapped[FeedbackReason] = mapped_column(
        SQLEnum(FeedbackReason, name="feedback_reason", native_enum=True),
        nullable=False,
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # Relationships
    profile: Mapped["Profile"] = relationship(
        "Profile",
        back_populates="feedback_entries",
    )
    job: Mapped["Job"] = relationship("Job")


class SkillAffinity(Base):
    """Per-profile learned affinity score per skill (plan §10)."""

    __tablename__ = "skill_affinities"

    profile_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("profiles.id", ondelete="CASCADE"),
        primary_key=True,
    )
    skill_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("skills.id", ondelete="CASCADE"),
        primary_key=True,
    )
    score: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
    )
    # Half-life in days for time-decayed affinity updates
    half_life_days: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=30.0,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        server_onupdate=func.now(),
    )
