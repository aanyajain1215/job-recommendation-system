"""Aggregate skill-disparity shapes (search / AI search / feed / direction)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class SkillDemand(BaseModel):
    """One skill's demand across a set of analysed jobs."""

    skill: str
    jobs: int = Field(ge=0, description="How many analysed jobs ask for this skill")
    share: float = Field(ge=0.0, le=1.0, description="jobs / jobs_analyzed")
    status: Literal["have", "transferable", "missing"] = "missing"


class SkillGapSummary(BaseModel):
    """Skill disparity across a whole result set, not one card.

    Built only from the per-card matched/missing/transferable classes the
    deterministic scorer already produced — no second formula, no LLM.
    """

    jobs_analyzed: int = Field(ge=0)
    avg_skill_match: float | None = Field(default=None, ge=0.0, le=100.0)
    top_missing: list[SkillDemand] = Field(default_factory=list)
    top_transferable: list[SkillDemand] = Field(default_factory=list)
    top_matched: list[SkillDemand] = Field(default_factory=list)
    headline: str | None = None


class DirectionGap(BaseModel):
    """What the market asks of one target role/domain vs. the seeker's skills."""

    target: str
    kind: Literal["role", "family"] = "role"
    jobs_analyzed: int = 0
    sources: list[str] = Field(default_factory=list)
    readiness: float | None = Field(
        default=None,
        ge=0.0,
        le=100.0,
        description="Demand-weighted coverage: have = 1, transferable = 0.5, missing = 0",
    )
    skills: list[SkillDemand] = Field(default_factory=list)
    top_missing: list[SkillDemand] = Field(default_factory=list)
    sample_jobs: list[dict[str, str | None]] = Field(default_factory=list)
    note: str | None = None


class DirectionGapResponse(BaseModel):
    targets: list[DirectionGap] = Field(default_factory=list)
    seeker_skill_count: int = 0
    message: str | None = None
