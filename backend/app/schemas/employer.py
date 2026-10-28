"""Employer-facing schemas (plan §E0: company profile + posting lifecycle).

Kept separate from app.schemas.user/job so the job-seeker payload shapes
stay untouched; E1-E5 (pipeline, reverse match, insights) extend this file.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import ApplicationStatus, ExperienceLevel, JobStatus


class CompanyDetailOut(BaseModel):
    """Full company profile — richer than CompanySummary (adds branding
    fields the job-seeker payload does not need)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    slug: str
    description: str | None = None
    website: str | None = None
    location: str | None = None
    logo_url: str | None = None
    industry: str | None = None
    company_size: str | None = None
    is_verified: bool = False

    # E0 convenience: how many live postings this company has, so the
    # company editor can show context without a second request.
    open_postings: int = 0


class CompanyUpdateRequest(BaseModel):
    """Partial update semantics: omit a field (or send null) to leave it
    unchanged; send an empty string to clear an optional field."""

    name: str | None = Field(default=None, min_length=2, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    website: str | None = Field(default=None, max_length=255)
    location: str | None = Field(default=None, max_length=150)
    logo_url: str | None = Field(default=None, max_length=500)
    industry: str | None = Field(default=None, max_length=100)
    company_size: str | None = Field(default=None, max_length=50)


class PostingStatusUpdate(BaseModel):
    status: JobStatus


class PipelineCounts(BaseModel):
    """Funnel counts per application stage, zero-filled for stable typing."""

    applied: int = 0
    viewed: int = 0
    shortlisted: int = 0
    interview: int = 0
    rejected: int = 0
    offer: int = 0
    saved: int = 0


class PostingPipelineOut(BaseModel):
    """E1: aggregate funnel for one posting (rows come from the existing
    GET /employer/jobs/{id}/applications endpoint)."""

    job_id: UUID
    title: str
    status: JobStatus
    total: int
    counts: PipelineCounts
    # freshness: applications received in the last 7 days
    recent_7d: int
    # pace = total / open days, so "2 applicants in 3 days" reads correctly
    days_open: int
    applications_per_day: float


# ---------------------------------------------------------------------------
# E2: reverse talent match (the seeker-facing engine run over the
# employer's OWN applicants only — the global talent pool stays private)
# ---------------------------------------------------------------------------
class TalentCandidateOut(BaseModel):
    application_id: UUID
    profile_id: UUID | None = None
    name: str
    headline: str | None = None
    location: str | None = None
    years_of_experience: float | None = None
    resume_url: str | None = None
    email: str | None = None
    status: ApplicationStatus
    applied_at: datetime
    # same 0-100 scale the candidate sees for this job (weights sum to 1)
    fit_score: float
    # per-component 0-100 breakdown — the "explainable fit" bars
    components: dict[str, float]
    matched_skills: list[str] = []
    missing_required: list[str] = []
    # skills the candidate lacks but can transfer into (skill2vec adjacency)
    transferable: list[str] = []


class PostingTalentOut(BaseModel):
    job_id: UUID
    title: str
    total_applicants: int
    # how many had a scorable profile (rows without one are excluded)
    scored: int
    job_skills: list[str] = []
    candidates: list[TalentCandidateOut] = []


# ---------------------------------------------------------------------------
# E3: insights — live JD feedback, market benchmark, supply/demand gaps
# ---------------------------------------------------------------------------
class JdCheck(BaseModel):
    label: str
    ok: bool
    detail: str


class JdHealth(BaseModel):
    """Deterministic JD feedback — no LLM, instant and free."""

    score: float  # 0-100, % of checks passed
    checks: list[JdCheck]


class SalaryBenchmark(BaseModel):
    """How this posting's pay compares to live peers in the same family
    (all figures FX-normalised to USD by the shared to_usd helper)."""

    family: str | None = None
    peer_jobs: int
    median_min_usd: float | None = None
    median_max_usd: float | None = None
    # where this posting's midpoint sits among peer midpoints (0-100)
    midpoint_percentile: float | None = None
    remote_share: float | None = None  # 0-1 among peers


class SkillMarketRow(BaseModel):
    skill: str
    # demand: live published jobs requiring the skill
    jobs_requiring: int
    # supply: how many job-seeker profiles hold it (AGGREGATE only — never
    # exposes who holds it, keeping the pool private)
    seekers_holding: int
    # demand - supply; positive = scarce in the market
    gap: int


class PostingInsightsOut(BaseModel):
    job_id: UUID
    title: str
    jd_health: JdHealth
    benchmark: SalaryBenchmark | None = None
    # this posting's required skills, scored against the market
    required_skill_market: list[SkillMarketRow] = []
    # most-required skills among live peers (JD completeness suggestions)
    family_top_demand: list[SkillMarketRow] = []


# ---------------------------------------------------------------------------
# E5: what-if relaxer — simulate loosening the posting's constraints.
# Simulation only; the posting is untouched until the employer applies it.
# ---------------------------------------------------------------------------
class WhatIfRequest(BaseModel):
    """Client-chosen relaxation to simulate. Empty = current state (baseline)."""

    # canonical skill names to un-require (validated against the posting)
    drop_required_skills: list[str] = []
    experience_level: ExperienceLevel | None = None
    is_remote: bool | None = None
    salary_min: int | None = Field(default=None, ge=0)
    salary_max: int | None = Field(default=None, ge=0)


class SkillRelaxOption(BaseModel):
    """Market reach if this ONE required skill were dropped (alone)."""

    skill: str
    reach_if_dropped: int
    # reach_if_dropped - baseline reach (>= 0: fewer constraints never shrink reach)
    gain: int


class WhatIfOut(BaseModel):
    job_id: UUID
    title: str
    # echo of what was simulated
    applied: WhatIfRequest
    # AGGREGATE market reach: seeker profiles holding EVERY required skill
    # (counts only — the pool itself stays private)
    reach_before: int
    reach_after: int
    total_seekers: int
    # own applicants only: avg fit score under the simulated posting
    applicants_scored: int
    avg_fit_before: float | None = None
    avg_fit_after: float | None = None
    # JD health recomputed under the simulated posting
    jd_health_before: float
    jd_health_after: float
    # ranked single-skill relaxation options (gain desc, relative to the
    # simulated state)
    drop_options: list[SkillRelaxOption] = []
    # human-readable outcomes
    effects: list[str] = []


# ---------------------------------------------------------------------------
# E4: performance analytics — time series, conversion, pipeline health
# ---------------------------------------------------------------------------
class DailyApplications(BaseModel):
    date: str  # ISO date (YYYY-MM-DD)
    count: int


class StageConversion(BaseModel):
    """% of applicants that reached each rung (side states excluded from
    the numerator but always in the denominator)."""

    viewed_rate: float  # viewed or beyond
    shortlist_rate: float  # shortlisted or beyond
    interview_rate: float  # interview or beyond
    offer_rate: float
    rejection_rate: float


class PostingPerformanceOut(BaseModel):
    job_id: UUID
    title: str
    total: int
    # daily application counts for the last 30 days (sparse days included)
    series: list[DailyApplications] = []
    conversion: StageConversion
    recent_7d: int
    days_since_last_application: int | None = None
    # avg days from apply → latest stage change, over candidates who moved
    avg_days_to_last_move: float | None = None
    # idle | hot | steady | stale — a coarse label for the health banner
    health: str
