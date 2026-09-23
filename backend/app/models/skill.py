from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, DateTime, Enum as SQLEnum, Float, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.enums import ProficiencyLevel, SkillSource

if TYPE_CHECKING:
    from app.models.job import Job
    from app.models.profile import Profile
    from app.models.skill_graph import SkillAlias


class Skill(Base):
    __tablename__ = "skills"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    name: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        index=True,
        nullable=False,
    )
    category: Mapped[str | None] = mapped_column(
        String(100),
        index=True,
        nullable=True,
    )
    # 384-d skill2vec/MiniLM embedding — powers skill_graph transfer similarity
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

    # Relationships
    profile_associations: Mapped[list["ProfileSkill"]] = relationship(
        "ProfileSkill",
        back_populates="skill",
        cascade="all, delete-orphan",
    )
    job_associations: Mapped[list["JobSkill"]] = relationship(
        "JobSkill",
        back_populates="skill",
        cascade="all, delete-orphan",
    )
    aliases: Mapped[list["SkillAlias"]] = relationship(
        "SkillAlias",
        back_populates="skill",
        cascade="all, delete-orphan",
    )


class ProfileSkill(Base):
    __tablename__ = "profile_skills"

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
    proficiency_level: Mapped[ProficiencyLevel | None] = mapped_column(
        SQLEnum(ProficiencyLevel, name="proficiency_level", native_enum=True),
        nullable=True,
    )
    years_of_experience: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )
    # Where the profile skill came from: "manual" | "resume"
    source: Mapped[SkillSource] = mapped_column(
        SQLEnum(SkillSource, name="profile_skill_source", native_enum=True),
        nullable=False,
        default=SkillSource.MANUAL,
        server_default="MANUAL",
    )

    # Relationships
    profile: Mapped["Profile"] = relationship("Profile", back_populates="skills")
    skill: Mapped["Skill"] = relationship("Skill", back_populates="profile_associations")


class JobSkill(Base):
    __tablename__ = "job_skills"

    job_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    skill_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("skills.id", ondelete="CASCADE"),
        primary_key=True,
    )
    is_required: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )
    importance_weight: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=1.0,
    )

    # Relationships
    job: Mapped["Job"] = relationship("Job", back_populates="skills")
    skill: Mapped["Skill"] = relationship("Skill", back_populates="job_associations")
