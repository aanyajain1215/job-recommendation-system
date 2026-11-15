from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, Enum as SQLEnum, Float, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.enums import SkillEdgeType

if TYPE_CHECKING:
    from app.models.skill import Skill


class SkillAlias(Base):
    """Alias → canonical skill mapping (e.g. 'ReactJS' → 'React')."""

    __tablename__ = "skill_aliases"
    __table_args__ = (
        UniqueConstraint("alias", name="uq_skill_alias_alias"),
        UniqueConstraint("normalized_alias", name="uq_skill_aliases_normalized_alias"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    alias: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
    )
    normalized_alias: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
        index=True,
    )
    skill_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("skills.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    confidence: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=1.0,
    )
    # "seed" | "llm" | "admin"
    source: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="seed",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if "normalized_alias" not in kwargs and self.alias:
            self.normalized_alias = " ".join(self.alias.strip().lower().split())

    # Relationships
    skill: Mapped["Skill"] = relationship("Skill", back_populates="aliases")


class SkillEdge(Base):
    """Directed edge in the skill graph: prereq | transfer | supersedes."""

    __tablename__ = "skill_edges"
    __table_args__ = (
        UniqueConstraint(
            "from_skill_id",
            "to_skill_id",
            "edge_type",
            name="uq_skill_edge",
        ),
        CheckConstraint(
            "from_skill_id != to_skill_id",
            name="ck_skill_edges_no_self_loop",
        ),
        CheckConstraint(
            "weight >= 0.0 AND weight <= 10.0",
            name="ck_skill_edges_weight_range",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    from_skill_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("skills.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    to_skill_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("skills.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    edge_type: Mapped[SkillEdgeType] = mapped_column(
        SQLEnum(SkillEdgeType, name="skill_edge_type", native_enum=True),
        nullable=False,
    )
    weight: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=1.0,
    )
    # "seed" | "skill2vec" | "llm" | "admin"
    source: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="seed",
    )
    approved: Mapped[bool] = mapped_column(
        nullable=False,
        default=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
