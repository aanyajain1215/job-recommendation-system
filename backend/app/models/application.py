from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum as SQLEnum, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.enums import ApplicationStatus

if TYPE_CHECKING:
    from app.models.job import Job
    from app.models.profile import Profile
    from app.models.user import User


class Application(Base):
    __tablename__ = "applications"
    __table_args__ = (
        UniqueConstraint("job_id", "user_id", name="uq_application_job_user"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    job_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
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
    status: Mapped[ApplicationStatus] = mapped_column(
        SQLEnum(ApplicationStatus, name="application_status", native_enum=True),
        nullable=False,
        default=ApplicationStatus.APPLIED,
        index=True,
    )
    cover_note: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    # Which resume version this application was submitted with (plan §3)
    resume_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("resumes.id", ondelete="SET NULL"),
        nullable=True,
    )
    resume_url_snapshot: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )
    applied_at: Mapped[datetime] = mapped_column(
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
    job: Mapped["Job"] = relationship("Job", back_populates="applications")
    user: Mapped["User"] = relationship("User", back_populates="applications")
    profile: Mapped["Profile"] = relationship("Profile", back_populates="applications")
