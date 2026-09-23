from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, DateTime, Enum as SQLEnum, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import TSVECTOR, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.enums import EmploymentType, ExperienceLevel, JobStatus

if TYPE_CHECKING:
    from app.models.application import Application
    from app.models.company import Company
    from app.models.interaction import Interaction
    from app.models.job_family import JobFamily
    from app.models.recommendation import Recommendation, SkillGap
    from app.models.skill import JobSkill
    from app.models.user import User


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint(
            "source",
            "external_id",
            name="uq_jobs_source_external_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    company_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    posted_by_user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    family_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("job_families.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # "native" | "adzuna" | "arbeitnow" | "remotive" | "jobicy"
    source: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="native",
        server_default="native",
        index=True,
    )
    external_id: Mapped[str | None] = mapped_column(
        String(120),
        nullable=True,
    )
    external_url: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )
    title: Mapped[str] = mapped_column(
        String(200),
        index=True,
        nullable=False,
    )
    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    requirements: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    employment_type: Mapped[EmploymentType] = mapped_column(
        SQLEnum(EmploymentType, name="employment_type", native_enum=True),
        nullable=False,
        default=EmploymentType.FULL_TIME,
        index=True,
    )
    experience_level: Mapped[ExperienceLevel] = mapped_column(
        SQLEnum(ExperienceLevel, name="experience_level", native_enum=True),
        nullable=False,
        default=ExperienceLevel.MID,
        index=True,
    )
    location: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
        index=True,
    )
    is_remote: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        index=True,
    )
    salary_min: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    salary_max: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    salary_currency: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        default="USD",
    )
    status: Mapped[JobStatus] = mapped_column(
        SQLEnum(JobStatus, name="job_status", native_enum=True),
        nullable=False,
        default=JobStatus.PUBLISHED,
        index=True,
    )
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(384),
        nullable=True,
    )
    embedding_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    search_vector = mapped_column(TSVECTOR, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        server_onupdate=func.now(),
    )

    # Relationships
    company: Mapped["Company"] = relationship("Company", back_populates="jobs")
    posted_by: Mapped["User"] = relationship("User", back_populates="posted_jobs")
    skills: Mapped[list["JobSkill"]] = relationship(
        "JobSkill",
        back_populates="job",
        cascade="all, delete-orphan",
    )
    applications: Mapped[list["Application"]] = relationship(
        "Application",
        back_populates="job",
        cascade="all, delete-orphan",
    )
    interactions: Mapped[list["Interaction"]] = relationship(
        "Interaction",
        back_populates="job",
        cascade="all, delete-orphan",
    )
    family: Mapped["JobFamily | None"] = relationship(
        "JobFamily",
        back_populates="jobs",
    )
    recommendations: Mapped[list["Recommendation"]] = relationship(
        "Recommendation",
        back_populates="job",
        cascade="all, delete-orphan",
    )
    skill_gaps: Mapped[list["SkillGap"]] = relationship(
        "SkillGap",
        back_populates="job",
        cascade="all, delete-orphan",
    )
