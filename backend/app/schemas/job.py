from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import EmploymentType, ExperienceLevel, JobStatus
from app.schemas.user import CompanySummary


class JobSkillRequirement(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    skill_name: str
    category: str | None = None
    is_required: bool = True
    importance_weight: float = 1.0


class JobSkillInput(BaseModel):
    skill_name: str = Field(min_length=1, max_length=100)
    is_required: bool = True
    importance_weight: float = Field(default=1.0, ge=0.1, le=5.0)


class JobCreateRequest(BaseModel):
    company_id: UUID | None = None
    title: str = Field(min_length=3, max_length=200)
    description: str = Field(min_length=10)
    requirements: str | None = None
    employment_type: EmploymentType = EmploymentType.FULL_TIME
    experience_level: ExperienceLevel = ExperienceLevel.MID
    location: str = Field(min_length=2, max_length=150)
    is_remote: bool = False
    salary_min: int | None = Field(default=None, ge=0)
    salary_max: int | None = Field(default=None, ge=0)
    salary_currency: str = Field(default="USD", max_length=10)
    skills: list[JobSkillInput] = []
    # canonical job-family name (unknown names are rejected); plan §5
    family: str | None = Field(default=None, max_length=100)


class JobUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=200)
    description: str | None = Field(default=None, min_length=10)
    requirements: str | None = None
    employment_type: EmploymentType | None = None
    experience_level: ExperienceLevel | None = None
    location: str | None = Field(default=None, min_length=2, max_length=150)
    is_remote: bool | None = None
    salary_min: int | None = Field(default=None, ge=0)
    salary_max: int | None = Field(default=None, ge=0)
    salary_currency: str | None = Field(default=None, max_length=10)
    status: JobStatus | None = None
    skills: list[JobSkillInput] | None = None
    # canonical job-family name ("" clears the family); plan §5
    family: str | None = Field(default=None, max_length=100)


class JobDetailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    company_id: UUID
    posted_by_user_id: UUID
    title: str
    description: str
    requirements: str | None = None
    employment_type: EmploymentType
    experience_level: ExperienceLevel
    location: str
    is_remote: bool
    salary_min: int | None = None
    salary_max: int | None = None
    salary_currency: str = "USD"
    status: JobStatus
    created_at: datetime
    updated_at: datetime
    company: CompanySummary
    skills: list[JobSkillRequirement] = []
    applicant_count: int = 0
    relevance_score: float | None = None
    snippet: str | None = None
    # ---- additive Phase 1 (plan §5/§13) ----
    family: str | None = None
    project_relevance: str | None = None


class JobListResponse(BaseModel):
    items: list[JobDetailResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class JobNlResponse(BaseModel):
    """NL search response (plan §17): results + the filters we parsed (§17)."""

    items: list[JobDetailResponse]
    total: int
    mode: str  # "llm" | "fts" (deterministic degrade)
    parsed_filters: dict[str, Any] = {}
    q: str
