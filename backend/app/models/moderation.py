"""Trust & safety flags raised against jobs, companies and user accounts.

The target is polymorphic (``target_type`` + ``target_id``) so one queue can
hold every kind of report. ``target_label`` snapshots the display name at
flag time, which keeps the queue readable even if the underlying row is later
removed.
"""

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum as SQLEnum, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.enums import FlagSeverity, FlagStatus, FlagTargetType

if TYPE_CHECKING:
    from app.models.user import User


class ModerationFlag(Base):
    __tablename__ = "moderation_flags"
    __table_args__ = (
        Index("ix_moderation_flags_status_type", "status", "target_type"),
        Index("ix_moderation_flags_target", "target_type", "target_id"),
        Index("ix_moderation_flags_created_at", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    target_type: Mapped[FlagTargetType] = mapped_column(
        SQLEnum(FlagTargetType, name="flag_target_type", native_enum=True),
        nullable=False,
    )
    target_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        nullable=False,
    )
    target_label: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    reason: Mapped[str] = mapped_column(
        String(160),
        nullable=False,
    )
    details: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    severity: Mapped[FlagSeverity] = mapped_column(
        SQLEnum(FlagSeverity, name="flag_severity", native_enum=True),
        nullable=False,
        default=FlagSeverity.MEDIUM,
    )
    status: Mapped[FlagStatus] = mapped_column(
        SQLEnum(FlagStatus, name="flag_status", native_enum=True),
        nullable=False,
        default=FlagStatus.OPEN,
        index=True,
    )
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    resolved_by_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    resolution_note: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_by: Mapped["User | None"] = relationship(
        "User",
        foreign_keys=[created_by_user_id],
    )
    resolved_by: Mapped["User | None"] = relationship(
        "User",
        foreign_keys=[resolved_by_user_id],
    )
