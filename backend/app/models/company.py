from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base

if TYPE_CHECKING:
    from app.models.job import Job
    from app.models.user import User


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    name: Mapped[str] = mapped_column(
        String(200),
        index=True,
        nullable=False,
    )
    slug: Mapped[str] = mapped_column(
        String(200),
        unique=True,
        index=True,
        nullable=False,
    )
    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    website: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    location: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )
    # e.g. "fintech", "healthtech", "saas" (plan §10 discovery filters)
    industry: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        index=True,
    )
    # e.g. "1-50", "51-200", "201-1000", "1000+"
    company_size: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )
    logo_url: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )
    is_verified: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    created_by_user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
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
    created_by: Mapped["User"] = relationship("User", back_populates="companies")
    jobs: Mapped[list["Job"]] = relationship(
        "Job",
        back_populates="company",
        cascade="all, delete-orphan",
    )
