from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base

if TYPE_CHECKING:
    from app.models.profile import Profile


class Resume(Base):
    """Versioned resume uploads with extraction evidence (plan §3, §20)."""

    __tablename__ = "resumes"

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
    file_path: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
    )
    original_filename: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    # "parsing" | "parsed" | "failed"
    parse_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="parsing",
    )
    parser_used: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
    )
    extracted: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    # Evidence spans: [{skill, start, end, quote}] — anti-hallucination source
    evidence: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # Relationships
    profile: Mapped["Profile"] = relationship("Profile", back_populates="resumes")


class Education(Base):
    __tablename__ = "education"

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
    degree: Mapped[str | None] = mapped_column(String(200), nullable=True)
    institution: Mapped[str | None] = mapped_column(String(200), nullable=True)
    field_of_study: Mapped[str | None] = mapped_column(String(200), nullable=True)
    grad_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_primary: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # Relationships
    profile: Mapped["Profile"] = relationship(
        "Profile",
        back_populates="education_rows",
    )


class Experience(Base):
    __tablename__ = "experience"

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
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    company: Mapped[str | None] = mapped_column(String(200), nullable=True)
    location: Mapped[str | None] = mapped_column(String(150), nullable=True)
    start_date: Mapped[str | None] = mapped_column(String(30), nullable=True)
    end_date: Mapped[str | None] = mapped_column(String(30), nullable=True)
    current: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    skills_used: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # Relationships
    profile: Mapped["Profile"] = relationship(
        "Profile",
        back_populates="experience_rows",
    )


class Project(Base):
    __tablename__ = "projects"

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
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    links: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    # Technologies detected from the project text (LLM P8 or manual)
    detected_skills: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default="[]",
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
        back_populates="project_rows",
    )


class Certification(Base):
    __tablename__ = "certifications"

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
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    issuer: Mapped[str | None] = mapped_column(String(150), nullable=True)
    issued_at: Mapped[str | None] = mapped_column(String(30), nullable=True)
    expires_at: Mapped[str | None] = mapped_column(String(30), nullable=True)
    credential_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # Relationships
    profile: Mapped["Profile"] = relationship(
        "Profile",
        back_populates="certification_rows",
    )
