from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base

if TYPE_CHECKING:
    from app.models.job import Job
    from app.models.profile import Profile


class JobFamily(Base):
    """Canonical job family / career role used for alternative-career discovery."""

    __tablename__ = "job_families"

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
    parent_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("job_families.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Median/must-have skills for this family (list of canonical skill names)
    core_skills: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    # Title keywords used for deterministic job→family assignment
    keywords: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # Relationships
    jobs: Mapped[list["Job"]] = relationship(
        "Job",
        back_populates="family",
    )
    profiles: Mapped[list["Profile"]] = relationship(
        "Profile",
        back_populates="target_family",
    )
