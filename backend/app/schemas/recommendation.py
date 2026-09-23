from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

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
    match_score: float = Field(ge=0.0, le=100.0, description="Overall match percentage (0-100)")
    skill_match_score: float = Field(ge=0.0, le=100.0, description="Explicit skill overlap percentage")
    content_similarity_score: float = Field(ge=0.0, le=100.0, description="Semantic (embedding) similarity percentage")
    matched_skills: list[str] = Field(default_factory=list, description="Skills possessed by seeker required or preferred by job")
    missing_skills: list[str] = Field(default_factory=list, description="Required job skills missing from seeker profile")
    match_reasons: list[str] = Field(default_factory=list, description="Human-readable explanation of why this job matches")
    # ---- additive Phase 1 fields (existing frontend keeps compiling) ----
    explanation: ExplanationSchema | None = None
    readiness: Readiness | None = None
    family: str | None = Field(default=None, description="Job family name")
    strategy: str = Field(default="deterministic", description="Ranking strategy that produced this item")
    model_version: str | None = Field(default=None, description="Learned model version when strategy used one")
    propensity: float | None = Field(
        default=None,
        description="Exploration propensity for this slot (1.0 = always shown; logged for IPS)",
    )


class RecommendationFeedResponse(BaseModel):
    items: list[RecommendationItem]
    total: int
    profile_completeness_score: float = Field(ge=0.0, le=100.0)
    recommendation_type: Literal["content_based", "cold_start"] = "content_based"
    recommendation_strategy: str = "hybrid_rrf_deterministic"
    # ---- additive Phase 1 fields ----
    strategy: str = "deterministic"
    model_version: str | None = None
    personalization_note: str | None = None
