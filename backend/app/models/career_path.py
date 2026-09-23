from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from sqlalchemy import (
    DateTime,
    Enum as SQLEnum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.enums import PathStatus, PathStepKind

if TYPE_CHECKING:
    from app.models.job_family import JobFamily
    from app.models.profile import Profile
    from app.models.skill import Skill


class CareerPath(Base):
    """Multi-step career path from a role to a target family (plan §7)."""

    __tablename__ = "career_paths"
    __table_args__ = (
        UniqueConstraint(
            "profile_id",
            "from_family_id",
            "to_family_id",
            name="uq_career_path_profile_route",
        ),
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
    from_family_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("job_families.id", ondelete="SET NULL"),
        nullable=True,
    )
    to_family_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("job_families.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Ordered roadmap: [{seq, kind, title, ...}] rendered from career_path_steps
    summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[PathStatus] = mapped_column(
        SQLEnum(PathStatus, name="path_status", native_enum=True),
        nullable=False,
        default=PathStatus.ACTIVE,
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

    # Relationships
    profile: Mapped["Profile"] = relationship(
        "Profile",
        back_populates="career_paths",
    )
    from_family: Mapped["JobFamily | None"] = relationship(
        "JobFamily",
        foreign_keys=[from_family_id],
    )
    to_family: Mapped["JobFamily"] = relationship(
        "JobFamily",
        foreign_keys=[to_family_id],
    )
    steps: Mapped[list["CareerPathStep"]] = relationship(
        "CareerPathStep",
        back_populates="path",
        order_by="CareerPathStep.seq",
        cascade="all, delete-orphan",
    )


class CareerPathStep(Base):
    """A single step in a career path (skill/project/cert with evidence)."""

    __tablename__ = "career_path_steps"
    __table_args__ = (
        UniqueConstraint("path_id", "seq", name="uq_career_path_step_seq"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    path_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("career_paths.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[PathStepKind] = mapped_column(
        SQLEnum(PathStepKind, name="path_step_kind", native_enum=True),
        nullable=False,
    )
    skill_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("skills.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Why this step: bridge evidence, e.g. family affinity delta
    rationale: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    # Step-level resources: [{title, url, kind, ...}]
    resources: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    est_hours: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
    )
    done_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Relationships
    path: Mapped["CareerPath"] = relationship(
        "CareerPath",
        back_populates="steps",
    )
    skill: Mapped["Skill | None"] = relationship("Skill")


class LearningResource(Base):
    """Approved learning resource mapped to a skill (plan §7)."""

    __tablename__ = "learning_resources"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    skill_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("skills.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # "article" | "video" | "course" | "docs" | "project"
    kind: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="article",
    )
    level: Mapped[str | None] = mapped_column(String(30), nullable=True)
    hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    quality_score: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.5,
    )
    approved: Mapped[bool] = mapped_column(
        nullable=False,
        default=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
