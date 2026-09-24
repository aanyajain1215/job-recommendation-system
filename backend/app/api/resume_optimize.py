"""Resume optimizer (plan §13/§18): POST /jobs/{id}/resume-optimize.

Layer 1 = deterministic ATS report over the seeker's resume evidence vs. the
job's extracted requirements.  Layer 2 = grounded P9 bullet critiques, run
through the anti-fabrication validator (skills outside evidence or the JD
gap list are dropped and counted).  Scores/numbers are never LLM-assigned.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.gap import load_job, load_profile
from app.core.db import get_db
from app.models.profile_entities import Resume
from app.models.user import User
from app.services import resume_improve
from app.services.embeddings import ensure_job_embeddings
from app.services.gap_engine import PARTIAL, STRONG, compare
from app.services.recommender import _ProfileContext
from app.services.skill_graph import fetch_graph

router = APIRouter(tags=["resume-optimize"])


class ResumeOptimizeResponse(BaseModel):
    job_id: UUID
    job_title: str
    ats: dict[str, Any]
    suggestions: list[dict[str, Any]]
    violations_dropped: int
    llm_used: bool
    disclaimer: str


def _resume_text(db: Session, profile) -> str:
    """Best-effort resume text: profile raw text → latest upload extract."""
    if profile.raw_resume_text and profile.raw_resume_text.strip():
        return profile.raw_resume_text
    latest = db.scalar(
        select(Resume)
        .where(Resume.profile_id == profile.id)
        .order_by(Resume.created_at.desc())
        .limit(1)
    )
    if latest is not None and isinstance(latest.extracted, dict):
        for key in ("raw_text", "text", "content"):
            value = latest.extracted.get(key)
            if isinstance(value, str) and value.strip():
                return value
    return ""


@router.post(
    "/jobs/{job_id}/resume-optimize",
    response_model=ResumeOptimizeResponse,
    summary="ATS report + grounded resume suggestions for one job",
)
def optimize_resume(
    job_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ResumeOptimizeResponse:
    """Plan §13: deterministic ATS layer always; LLM layer grounded to spans."""
    profile = load_profile(db, current_user.id)
    job = load_job(db, job_id)

    ensure_job_embeddings([job])
    ctx = _ProfileContext(profile)
    inputs = ctx.inputs_for(job)
    gap = compare(inputs, graph=fetch_graph(db))

    resume_text = _resume_text(db, profile)

    # demonstrated evidence: canonical profile skills + strong/partial gap hits
    evidence = {
        ps.skill.name
        for ps in profile.skills
        if ps.skill is not None and ps.skill.name
    }
    evidence.update(
        item.skill for item in gap.items if item.status in (STRONG, PARTIAL)
    )

    jd_required = [item.skill for item in gap.items if item.required]
    gap_skills = list(gap.missing)

    out = resume_improve.optimize(
        resume_text=resume_text,
        evidence_tokens=evidence,
        jd_required=jd_required,
        gap_skills=gap_skills,
        profile=profile,
    )

    return ResumeOptimizeResponse(
        job_id=job.id,
        job_title=job.title,
        ats=out["ats"],
        suggestions=out["suggestions"],
        violations_dropped=out["violations_dropped"],
        llm_used=out["llm_used"],
        disclaimer=out["disclaimer"],
    )
