"""Project relevance mapping (plan §14/§18) — both §13 directions.

- GET /jobs/{id}/project-map        → which of *my* projects back this job
- GET /profiles/me/project-benefits → which families each project benefits
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.gap import load_job, load_profile
from app.core.db import get_db
from app.models.job_family import JobFamily
from app.models.user import User
from app.services import project_mapping as pm
from app.services.embeddings import ensure_job_embeddings
from app.services.recommender import _ProfileContext

router = APIRouter(tags=["projects"])


class ProjectMapItem(BaseModel):
    project_id: UUID | None
    title: str
    score: float
    band: str
    matched_skills: list[str] = []


class ProjectMapResponse(BaseModel):
    job_id: UUID
    job_title: str
    items: list[ProjectMapItem]
    best: ProjectMapItem | None = None
    powered_by: str | None = None


class FamilyBenefit(BaseModel):
    family: str
    score: float
    band: str


class ProjectBenefitItem(BaseModel):
    project_id: str
    title: str
    benefits: list[FamilyBenefit] = []


class ProjectBenefitsResponse(BaseModel):
    items: list[ProjectBenefitItem] = []


@router.get(
    "/jobs/{job_id}/project-map",
    response_model=ProjectMapResponse,
    summary="Which of my projects are relevant to this job (§13/§14)",
)
def job_project_map(
    job_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ProjectMapResponse:
    """Deterministic band mapping — same job_skills the scorer consumed."""
    profile = load_profile(db, current_user.id)
    job = load_job(db, job_id)

    ensure_job_embeddings([job])
    ctx = _ProfileContext(profile)
    inputs = ctx.inputs_for(job)

    ranked = pm.rank_projects(profile.project_rows, inputs.job_skills)
    items = [ProjectMapItem(**row.as_dict()) for row in ranked]
    best = items[0] if items and items[0].score > 0 else None

    return ProjectMapResponse(
        job_id=job.id,
        job_title=job.title,
        items=items,
        best=best,
        powered_by=pm.powered_by_label(profile.project_rows, inputs.job_skills),
    )


@router.get(
    "/profiles/me/project-benefits",
    response_model=ProjectBenefitsResponse,
    summary="Which job families each of my projects benefits (§14)",
)
def my_project_benefits(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ProjectBenefitsResponse:
    """Profile direction: 'This project benefits: X (Very high), Y (High)…'"""
    profile = load_profile(db, current_user.id)
    families = db.scalars(select(JobFamily)).all()
    items = pm.family_benefits(profile.project_rows, families)
    return ProjectBenefitsResponse(
        items=[ProjectBenefitItem(**row) for row in items]
    )
