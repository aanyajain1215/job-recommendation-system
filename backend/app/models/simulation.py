from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base

if TYPE_CHECKING:
    from app.models.profile import Profile


class Simulation(Base):
    """What-If simulator run: mutation in, score deltas out (plan §9)."""

    __tablename__ = "simulations"

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
    # e.g. {kind: "add_skill", value: "Docker"} or {kind: "add_project", ...}
    mutation: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    # Before/after aggregates: {before: {...}, after: {...}, deltas: [...]}
    result_delta: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # Relationships
    profile: Mapped["Profile"] = relationship(
        "Profile",
        back_populates="simulations",
    )
