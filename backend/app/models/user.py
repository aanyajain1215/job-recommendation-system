from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, Enum as SQLEnum, String, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.enums import UserRole

if TYPE_CHECKING:
    from app.models.application import Application
    from app.models.company import Company
    from app.models.interaction import Interaction
    from app.models.job import Job
    from app.models.profile import Profile


class User(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        index=True,
        nullable=False,
    )
    hashed_password: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    role: Mapped[UserRole] = mapped_column(
        SQLEnum(UserRole, name="user_role", native_enum=True),
        nullable=False,
        default=UserRole.JOB_SEEKER,
        index=True,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )
    is_verified: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
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
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )
    companies: Mapped[list["Company"]] = relationship(
        "Company",
        back_populates="created_by",
        cascade="all, delete-orphan",
    )
    posted_jobs: Mapped[list["Job"]] = relationship(
        "Job",
        back_populates="posted_by",
        cascade="all, delete-orphan",
    )
    applications: Mapped[list["Application"]] = relationship(
        "Application",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    interactions: Mapped[list["Interaction"]] = relationship(
        "Interaction",
        back_populates="user",
        cascade="all, delete-orphan",
    )
