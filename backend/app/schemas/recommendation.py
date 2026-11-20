from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import RecommendationEventType
from app.schemas.job import JobDetailResponse


class Readiness(BaseModel):
    """Application readiness band (plan §12; calibrated by M3 in Phase 3)."""

    value: float = Field(ge=0.0, le=1.0)
    band: Literal["low", "medium", "high"]


class ExplanationSchema(BaseModel):
    """§12 explanation contract — components/contributions are verbatim
    from the deterministic scorer (the LLM never writes these numbers)."""

    model_config = ConfigDict(from_attributes=True)

    summary: str
    components: dict[str, float]
    contributions: dict[str, float]
    strengths: list[str] = Field(default_factory=list)
    concerns: list[str] = Field(default_factory=list)
    recommended_action: str = ""
    delta_note: str | None = None


class RecommendationItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    job: JobDetailResponse
    recommendation_id: UUID | None = Field(
        default=None,
        description="ID of the persisted recommendation record (for event tracking and feedback linkage)",
    )
    match_score: float = Field(ge=0.0, le=100.0, description="Overall match percentage (0-100)")
    skill_match_score: float = Field(ge=0.0, le=100.0, description="Explicit skill overlap percentage")
    content_similarity_score: float = Field(ge=0.0, le=100.0, description="Semantic (embedding) similarity percentage")
    matched_skills: list[str] = Field(default_factory=list, description="Skills possessed by seeker required or preferred by job")
    missing_skills: list[str] = Field(default_factory=list, description="Required job skills missing from seeker profile")
    match_reasons: list[str] = Field(default_factory=list, description="Human-readable explanation of why this job matches")
    # ---- additive Phase 1 & 2 fields ----
    explanation: ExplanationSchema | None = None
    readiness: Readiness | None = None
    match_tier: Literal["top", "strong", "possible"] | None = Field(
        default=None,
        description=("Label shown instead of a raw %: top = >=2x the average apply rate, "
                     "strong = above average, possible = below (M3-calibrated)"),
    )
    family: str | None = Field(default=None, description="Job family name")
    strategy: str = Field(default="deterministic", description="Ranking strategy that produced this item")
    model_version: str | None = Field(default=None, description="Learned model version when strategy used one")
    propensity: float | None = Field(
        default=None,
        description="Exploration propensity for this slot (1.0 = always shown; logged for IPS)",
    )
    bandit: dict | None = Field(default=None, description="Bandit/RL exploration metadata when applicable")


class RecommendationFeedResponse(BaseModel):
    items: list[RecommendationItem]
    total: int
    profile_completeness_score: float = Field(ge=0.0, le=100.0)
    recommendation_type: Literal["content_based", "cold_start"] = "content_based"
    recommendation_strategy: str = "hybrid_rrf_deterministic"
    strategy: str = "deterministic"
    model_version: str | None = None
    personalization_note: str | None = None


class RecommendationEventCreate(BaseModel):
    recommendation_id: UUID
    event_type: RecommendationEventType
    rank: int | None = Field(default=None, ge=1)
    request_id: str | None = Field(default=None, max_length=100)
    metadata: dict[str, Any] | None = None


class RecommendationEventOut(BaseModel):
    id: UUID
    recommendation_id: UUID | None
    profile_id: UUID
    event_type: RecommendationEventType
    occurred_at: datetime
    rank: int | None = None
    request_id: str | None = None
    metadata: dict[str, Any] | None = None
