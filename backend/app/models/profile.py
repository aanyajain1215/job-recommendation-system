from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, Enum as SQLEnum, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.enums import WorkMode

if TYPE_CHECKING:
    from app.models.application import Application
    from app.models.career_path import CareerPath
    from app.models.feedback import Feedback
    from app.models.job_family import JobFamily
    from app.models.profile_entities import (
        Certification,
        Education,
        Experience,
        Project,
        Resume,
    )
    from app.models.skill import ProfileSkill
    from app.models.simulation import Simulation
    from app.models.user import User


class Profile(Base):
    __tablename__ = "profiles"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    first_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default="",
    )
    last_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default="",
    )
    headline: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    bio: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    location: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
        index=True,
    )
    phone: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )
    resume_url: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )
    raw_resume_text: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    parsed_resume_data: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    years_of_experience: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )
    education: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    work_experience: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    # ---- Preferences (plan §2/§18) ----
    expected_salary_min: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    expected_salary_max: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    expected_salary_currency: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        default="USD",
        server_default="USD",
    )
    target_job_family_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("job_families.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    preferred_work_mode: Mapped[WorkMode | None] = mapped_column(
        SQLEnum(WorkMode, name="work_mode", native_enum=True),
        nullable=True,
    )
    career_interests: Mapped[list[str] | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    preferred_locations: Mapped[list[str] | None] = mapped_column(
        ARRAY(String(150)),
        nullable=True,
    )
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(384),
        nullable=True,
    )
    embedding_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
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
    user: Mapped["User"] = relationship("User", back_populates="profile")
    skills: Mapped[list["ProfileSkill"]] = relationship(
        "ProfileSkill",
        back_populates="profile",
        cascade="all, delete-orphan",
    )
    applications: Mapped[list["Application"]] = relationship(
        "Application",
        back_populates="profile",
        cascade="all, delete-orphan",
    )
    resumes: Mapped[list["Resume"]] = relationship(
        "Resume",
        back_populates="profile",
        cascade="all, delete-orphan",
    )
    education_rows: Mapped[list["Education"]] = relationship(
        "Education",
        back_populates="profile",
        cascade="all, delete-orphan",
    )
    experience_rows: Mapped[list["Experience"]] = relationship(
        "Experience",
        back_populates="profile",
        cascade="all, delete-orphan",
    )
    project_rows: Mapped[list["Project"]] = relationship(
        "Project",
        back_populates="profile",
        cascade="all, delete-orphan",
    )
    certification_rows: Mapped[list["Certification"]] = relationship(
        "Certification",
        back_populates="profile",
        cascade="all, delete-orphan",
    )
    feedback_entries: Mapped[list["Feedback"]] = relationship(
        "Feedback",
        back_populates="profile",
        cascade="all, delete-orphan",
    )
    simulations: Mapped[list["Simulation"]] = relationship(
        "Simulation",
        back_populates="profile",
        cascade="all, delete-orphan",
    )
    career_paths: Mapped[list["CareerPath"]] = relationship(
        "CareerPath",
        back_populates="profile",
        cascade="all, delete-orphan",
    )
    target_family: Mapped["JobFamily | None"] = relationship(
        "JobFamily",
        back_populates="profiles",
    )
