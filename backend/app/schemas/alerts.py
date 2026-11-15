from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


DigestFrequency = Literal["daily", "weekly", "off"]


class AlertSettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    enabled: bool
    email_enabled: bool
    digest_frequency: str
    min_score: float
    max_items: int
    last_digest_at: datetime | None = None
    updated_at: datetime | None = None


class AlertSettingsUpdate(BaseModel):
    enabled: bool | None = None
    email_enabled: bool | None = None
    digest_frequency: DigestFrequency | None = None
    min_score: float | None = Field(default=None, ge=0.0, le=100.0)
    max_items: int | None = Field(default=None, ge=1, le=20)


class AlertJobOut(BaseModel):
    id: UUID
    title: str
    company_name: str | None = None
    location: str | None = None
    is_remote: bool = False
    employment_type: str | None = None
    experience_level: str | None = None
    salary_min: int | None = None
    salary_max: int | None = None
    salary_currency: str = "USD"
    created_at: datetime | None = None


class AlertMatchOut(BaseModel):
    job: AlertJobOut
    score: float = Field(ge=0.0, le=100.0)
    seed_job_id: UUID
    seed_job_title: str
    reason: str
    matched_skills: list[str] = Field(default_factory=list)


class AlertPreviewOut(BaseModel):
    items: list[AlertMatchOut]
    seeds_used: int
    candidates_scanned: int
    min_score: float
    generated_at: datetime


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    type: str
    title: str
    body: str | None = None
    link: str | None = None
    read_at: datetime | None = None
    created_at: datetime


class NotificationListOut(BaseModel):
    items: list[NotificationOut]
    total: int
    unread: int


class NotificationReadOut(BaseModel):
    id: UUID
    read_at: datetime


class NotificationReadAllOut(BaseModel):
    marked: int
