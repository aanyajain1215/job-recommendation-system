"""Skill Gap endpoint (plan §18): GET /recommendations/{job_id}/gap."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_current_user
from app.core.db import get_db
from app.models.job import Job
from app.models.profile import Profile
from app.models.skill import JobSkill, ProfileSkill
from app.models.user import User
from app.services.embeddings import ensure_job_embeddings
from app.services.explanation import readiness_from_score
from app.services.gap_engine import compare
from app.services.recommender import _ProfileContext
from app.services.scoring import score_pair
from app.services.skill_graph import fetch_graph

router = APIRouter(prefix="/recommendations", tags=["gap"])


# ---------------------------------------------------------------------------
# Shared loaders (also used by api/roadmap.py — one code path)
# ---------------------------------------------------------------------------

def load_profile(db: Session, user_id: UUID) -> Profile:
    profile = db.scalar(
        select(Profile)
        .where(Profile.user_id == user_id)
        .options(
            selectinload(Profile.skills).selectinload(ProfileSkill.skill),
            selectinload(Profile.project_rows),
            selectinload(Profile.target_family),
        )
    )
    if profile is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    return profile


def load_job(db: Session, job_id: UUID) -> Job:
    job = db.scalar(
        select(Job)
        .where(Job.id == job_id)
        .options(
            selectinload(Job.skills).selectinload(JobSkill.skill),
            selectinload(Job.family),
            selectinload(Job.company),
        )
    )
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


# ---------------------------------------------------------------------------
# Response schema
# ---------------------------------------------------------------------------

class GapResponse(BaseModel):
    job_id: UUID
    job_title: str
    # Deterministic engine numbers (verbatim — the LLM never writes these)
    match_score: float
    gap_score: float
    readiness: dict[str, Any]
    classes: list[dict[str, Any]]
    counts: dict[str, int]
    missing_required: list[str]
    weakest_link: str | None
    reasons: list[str]


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

@router.get("/{job_id}/gap", response_model=GapResponse)
def get_job_gap(
    job_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> GapResponse:
    """Four-class skill gap for one job (plan §8).

    Uses the exact ComponentInputs the recommendation scorer consumed, so
    `gap_score` equals the card's skill-match score by construction.
    """
    profile = load_profile(db, current_user.id)
    job = load_job(db, job_id)

    ensure_job_embeddings([job])
    ctx = _ProfileContext(profile)
    inputs = ctx.inputs_for(job)
    gap = compare(inputs, graph=fetch_graph(db))

    final = score_pair(inputs).final

    return GapResponse(
        job_id=job.id,
        job_title=job.title,
        match_score=round(final, 2),
        gap_score=round(gap.gap_score, 2),
        readiness=readiness_from_score(final),
        classes=gap.classes,
        counts=gap.counts,
        missing_required=gap.missing_required,
        weakest_link=gap.weakest_link,
        reasons=gap.reasons,
    )
