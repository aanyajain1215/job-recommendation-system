from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import ProficiencyLevel, WorkMode


class ProfileSkillItem(BaseModel):
    skill_name: str
    category: str | None = None
    proficiency_level: ProficiencyLevel | None = None
    years_of_experience: float | None = None


class EducationItem(BaseModel):
    degree: str
    institution: str
    field_of_study: str | None = None
    start_year: int | None = None
    end_year: int | None = None


class ExperienceItem(BaseModel):
    title: str
    company: str
    location: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    current: bool = False
    description: str | None = None


class ProfileUpdateRequest(BaseModel):
    first_name: str | None = Field(default=None, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    headline: str | None = Field(default=None, max_length=255)
    bio: str | None = None
    location: str | None = Field(default=None, max_length=150)
    phone: str | None = Field(default=None, max_length=50)
    years_of_experience: float | None = Field(default=None, ge=0)
    skills: list[ProfileSkillItem] | None = None
    education: list[EducationItem] | None = None
    work_experience: list[ExperienceItem] | None = None
    # ---- additive Phase 1: preferences (plan §2/§18); None = leave unchanged,
    # "" where noted clears ----
    expected_salary_min: int | None = Field(default=None, ge=0)
    expected_salary_max: int | None = Field(default=None, ge=0)
    expected_salary_currency: str | None = Field(default=None, max_length=10)
    preferred_work_mode: WorkMode | None = None
    career_interests: list[str] | None = None
    preferred_locations: list[str] | None = None
    # canonical job-family name; "" clears the target family
    target_family: str | None = Field(default=None, max_length=100)


# ---------------------------------------------------------------------------
# Structured sub-resources (plan §3 — resumes/education/experience/projects/
# certifications; additive alongside the legacy JSONB education/work_experience)
# ---------------------------------------------------------------------------


class EducationCreateRequest(BaseModel):
    degree: str | None = Field(default=None, max_length=200)
    institution: str | None = Field(default=None, max_length=200)
    field_of_study: str | None = Field(default=None, max_length=200)
    grad_year: int | None = Field(default=None, ge=1950, le=2100)
    is_primary: bool = False


class EducationUpdateRequest(BaseModel):
    degree: str | None = Field(default=None, max_length=200)
    institution: str | None = Field(default=None, max_length=200)
    field_of_study: str | None = Field(default=None, max_length=200)
    grad_year: int | None = Field(default=None, ge=1950, le=2100)
    is_primary: bool | None = None


class EducationResponse(EducationCreateRequest):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime


class ExperienceCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    company: str | None = Field(default=None, max_length=200)
    location: str | None = Field(default=None, max_length=150)
    start_date: str | None = Field(default=None, max_length=30)
    end_date: str | None = Field(default=None, max_length=30)
    current: bool = False
    description: str | None = None
    skills_used: list[str] | None = None


class ExperienceUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    company: str | None = Field(default=None, max_length=200)
    location: str | None = Field(default=None, max_length=150)
    start_date: str | None = Field(default=None, max_length=30)
    end_date: str | None = Field(default=None, max_length=30)
    current: bool | None = None
    description: str | None = None
    skills_used: list[str] | None = None


class ExperienceResponse(ExperienceCreateRequest):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime


class ProjectCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    links: list[str] | None = None
    detected_skills: list[str] = Field(default_factory=list)


class ProjectUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    links: list[str] | None = None
    detected_skills: list[str] | None = None


class ProjectResponse(ProjectCreateRequest):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime
    updated_at: datetime


class CertificationCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    issuer: str | None = Field(default=None, max_length=150)
    issued_at: str | None = Field(default=None, max_length=30)
    expires_at: str | None = Field(default=None, max_length=30)
    credential_url: str | None = Field(default=None, max_length=500)


class CertificationUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    issuer: str | None = Field(default=None, max_length=150)
    issued_at: str | None = Field(default=None, max_length=30)
    expires_at: str | None = Field(default=None, max_length=30)
    credential_url: str | None = Field(default=None, max_length=500)


class CertificationResponse(CertificationCreateRequest):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime


class ResumeResponse(BaseModel):
    """Versioned resume upload status (evidence kept server-side, plan §3)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    original_filename: str | None = None
    parse_status: str
    parser_used: str | None = None
    created_at: datetime


class ProfileDetailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    first_name: str
    last_name: str
    headline: str | None = None
    bio: str | None = None
    location: str | None = None
    phone: str | None = None
    resume_url: str | None = None
    raw_resume_text: str | None = None
    parsed_resume_data: dict[str, Any] | None = None
    years_of_experience: float | None = None
    education: list[dict[str, Any]] | None = None
    work_experience: list[dict[str, Any]] | None = None
    skills: list[ProfileSkillItem] = []
    created_at: datetime
    updated_at: datetime
    # ---- additive Phase 1 (existing frontend keeps compiling) ----
    expected_salary_min: int | None = None
    expected_salary_max: int | None = None
    expected_salary_currency: str = "USD"
    preferred_work_mode: WorkMode | None = None
    career_interests: list[str] | None = None
    preferred_locations: list[str] | None = None
    target_family: str | None = None
    education_rows: list[EducationResponse] = []
    experience_rows: list[ExperienceResponse] = []
    project_rows: list[ProjectResponse] = []
    certification_rows: list[CertificationResponse] = []
    resumes: list[ResumeResponse] = []
