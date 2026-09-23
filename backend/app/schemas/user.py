from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr

from app.models.enums import UserRole


class ProfileSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    first_name: str
    last_name: str
    headline: str | None = None
    location: str | None = None
    resume_url: str | None = None
    years_of_experience: float | None = None


class CompanySummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    slug: str
    location: str | None = None
    website: str | None = None
    is_verified: bool = False
    # additive Phase 1: filter facets (plan §10/§17)
    industry: str | None = None
    company_size: str | None = None


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: EmailStr
    role: UserRole
    is_active: bool
    is_verified: bool
    created_at: datetime
    profile: ProfileSummary | None = None
    companies: list[CompanySummary] = []
