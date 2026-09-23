"""Alternative Career Discovery endpoint (plan §18): GET /careers/discover

Affinity is computed with the gap engine's four-class rule and blended
with embedding cosine — suggestions ≥ τ (default 55.0), current target
family excluded, presets rendered through the same math (plan §11).
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.gap import load_profile
from app.core.db import get_db
from app.models.job_family import JobFamily
from app.models.skill import Skill
from app.models.user import User
from app.services.career_discovery import discover
from app.services.recommender import _ProfileContext
from app.services.skill_graph import fetch_graph

router = APIRouter(prefix="/careers", tags=["careers"])

# Curated starter suggestions rendered with the exact same affinity math —
# never a second formula (plan §11).
PRESET_FAMILIES = [
    "Machine Learning Engineering",
    "Data Science",
    "DevOps Engineering",
    "Data Analytics",
]


class DiscoverResponse(BaseModel):
    threshold: float
    target_family: str | None
    suggestions: list[dict[str, Any]]
    presets: list[dict[str, Any]]
    explored: int


@router.get("/discover", response_model=DiscoverResponse)
def discover_careers(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> DiscoverResponse:
    """Alternative career directions with evidence explanations (plan §11)."""
    profile = load_profile(db, current_user.id)
    families = list(db.scalars(select(JobFamily).order_by(JobFamily.name)).all())
    skills = list(db.scalars(select(Skill)).all())

    skill_embeddings = {
        str(s.name).lower().strip(): s.embedding
        for s in skills
        if s.embedding is not None
    }

    ctx = _ProfileContext(profile)  # computes/refreshes the profile embedding
    profile_embedding = profile.embedding

    result = discover(
        families=families,
        seeker_skills=ctx.seeker_skills,
        graph=fetch_graph(db),
        profile_embedding=profile_embedding,
        skill_embeddings=skill_embeddings,
        target_family=profile.target_family,
        preset_names=PRESET_FAMILIES,
    )
    return DiscoverResponse(**result)
