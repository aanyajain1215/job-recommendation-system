from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import ApplicationStatus, EmploymentType, ExperienceLevel
from app.schemas.user import CompanySummary


class ApplicationCreate(BaseModel):
    job_id: UUID | None = None
    cover_note: str | None = Field(default=None, max_length=5000)


class JobSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    location: str
    is_remote: bool
    employment_type: EmploymentType
    experience_level: ExperienceLevel
    salary_min: int | None = None
    salary_max: int | None = None
    salary_currency: str = "USD"
    company: CompanySummary | None = None


class ApplicationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    job_id: UUID
    user_id: UUID
    status: ApplicationStatus
    cover_note: str | None = None
    resume_url_snapshot: str | None = None
    applied_at: datetime
    created_at: datetime | None = None
    updated_at: datetime
    job: JobSummaryOut | None = None

    def __init__(self, **data):
        if "applied_at" in data and "created_at" not in data:
            data["created_at"] = data["applied_at"]
        super().__init__(**data)


class ApplicationStatsOut(BaseModel):
    total_applied: int
    applied: int
    viewed: int
    shortlisted: int
    interview: int
    rejected: int
    offer: int


class ApplicantProfileSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    first_name: str
    last_name: str
    headline: str | None = None
    location: str | None = None
    phone: str | None = None
    resume_url: str | None = None
    years_of_experience: float | None = None


class EmployerApplicationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    job_id: UUID
    user_id: UUID
    status: ApplicationStatus
    cover_note: str | None = None
    resume_url_snapshot: str | None = None
    applied_at: datetime
    created_at: datetime | None = None
    updated_at: datetime
    applicant: ApplicantProfileSummary | None = None
    user_email: str | None = None

    def __init__(self, **data):
        if "applied_at" in data and "created_at" not in data:
            data["created_at"] = data["applied_at"]
        super().__init__(**data)


class ApplicationStatusUpdate(BaseModel):
    status: ApplicationStatus
