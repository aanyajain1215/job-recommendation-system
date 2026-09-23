"""Career Roadmap endpoints (plan §18):
    GET  /recommendations/{job_id}/roadmap
    POST /roadmaps/{path_id}/steps/{step_id}/complete

The GET persists a CareerPath (+steps once) so the POST has something to
advance; regenerated content lives in the response while completion state
lives in the rows (never clobbered by a re-read).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.gap import load_job, load_profile
from app.core.db import get_db
from app.models.career_path import CareerPath, CareerPathStep
from app.models.enums import PathStatus, PathStepKind
from app.models.skill import Skill
from app.models.user import User
from app.services.embeddings import ensure_job_embeddings
from app.services.gap_engine import compare
from app.services.recommender import _ProfileContext
from app.services.roadmap import build_roadmap
from app.services.skill_graph import fetch_graph

router = APIRouter(prefix="/recommendations", tags=["roadmap"])
actions_router = APIRouter(prefix="/roadmaps", tags=["roadmap"])


class RoadmapResponse(BaseModel):
    id: UUID | None
    job_id: UUID
    job_title: str
    steps: list[dict[str, Any]]
    phases: list[dict[str, Any]]
    candidates: list[str]
    effort_band: str
    total_hours: float
    readiness_before: dict[str, Any]
    readiness_after: dict[str, Any]
    summary: str


class StepCompleteResponse(BaseModel):
    step_id: UUID
    path_id: UUID
    seq: int
    done_at: datetime
    path_status: str
    steps_done: int
    steps_total: int


def _skill_ids_by_name(db: Session, names: set[str]) -> dict[str, UUID]:
    if not names:
        return {}
    lowered = sorted(n.lower() for n in names)
    rows = db.execute(
        select(Skill.id, Skill.name).where(func.lower(Skill.name).in_(lowered))
    ).all()
    return {str(name).lower(): sid for sid, name in rows}


def _persist_path(
    db: Session,
    profile: Any,
    job: Any,
    result: Any,
) -> UUID | None:
    """Upsert the CareerPath for this (profile, job family) route and create
    steps the first time.  Returns the path id, or None when the job has no
    family to anchor a route on (response is still fully usable)."""
    if job.family_id is None:
        return None

    path = db.scalar(
        select(CareerPath).where(
            CareerPath.profile_id == profile.id,
            CareerPath.to_family_id == job.family_id,
        )
    )
    if path is None:
        path = CareerPath(
            profile_id=profile.id,
            from_family_id=profile.target_job_family_id,
            to_family_id=job.family_id,
            summary=result.as_dict(),
            status=PathStatus.ACTIVE,
        )
        db.add(path)
        db.flush()
    else:
        path.summary = result.as_dict()

    if not path.steps:
        ids = _skill_ids_by_name(
            db, {s.skill for s in result.steps if s.skill}
        )
        for step in result.steps:
            db.add(
                CareerPathStep(
                    path_id=path.id,
                    seq=step.seq,
                    kind=(
                        PathStepKind.SKILL
                        if step.kind == "skill"
                        else PathStepKind.PROJECT
                    ),
                    skill_id=ids.get((step.skill or "").lower()),
                    title=step.title[:200],
                    description=None,
                    rationale=step.rationale,
                    resources=None,
                    est_hours=step.est_hours,
                )
            )
    db.commit()
    return path.id


@router.get("/{job_id}/roadmap", response_model=RoadmapResponse)
def get_job_roadmap(
    job_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> RoadmapResponse:
    """Deterministic roadmap for this profile↔job route (plan §9)."""
    profile = load_profile(db, current_user.id)
    job = load_job(db, job_id)

    ensure_job_embeddings([job])
    ctx = _ProfileContext(profile)
    inputs = ctx.inputs_for(job)
    graph = fetch_graph(db)
    gap = compare(inputs, graph=graph)
    result = build_roadmap(profile, job, gap, inputs, graph)

    path_id = _persist_path(db, profile, job, result)

    # Decorate the generated content with persisted completion state: the
    # client needs each step's row UUID to POST a completion and its done
    # flag to render progress on re-read (plan §18).  Content stays
    # deterministic; only id/done reflect the rows.
    steps_payload = [s.as_dict() for s in result.steps]
    phases_payload = [p.as_dict() for p in result.phases]

    step_rows: dict[int, CareerPathStep] = {}
    if path_id is not None:
        step_rows = {
            row.seq: row
            for row in db.execute(
                select(CareerPathStep).where(CareerPathStep.path_id == path_id)
            ).scalars()
        }

    def _decorate(step: dict[str, Any]) -> dict[str, Any]:
        row = step_rows.get(step["seq"])
        step["id"] = str(row.id) if row is not None else None
        step["done"] = bool(row is not None and row.done_at is not None)
        return step

    steps_payload = [_decorate(d) for d in steps_payload]
    for phase in phases_payload:
        phase["steps"] = [_decorate(d) for d in phase["steps"]]

    return RoadmapResponse(
        id=path_id,
        job_id=job.id,
        job_title=job.title,
        steps=steps_payload,
        phases=phases_payload,
        candidates=result.candidates,
        effort_band=result.effort_band,
        total_hours=result.total_hours,
        readiness_before=result.readiness_before,
        readiness_after=result.readiness_after,
        summary=result.summary,
    )


@actions_router.post(
    "/{path_id}/steps/{step_id}/complete",
    response_model=StepCompleteResponse,
)
def complete_roadmap_step(
    path_id: UUID,
    step_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> StepCompleteResponse:
    """Mark one roadmap step done (plan §18). Idempotent: re-completing
    keeps the first done_at and returns the same state."""
    path = db.get(CareerPath, path_id)
    if path is None:
        raise HTTPException(status_code=404, detail="Roadmap not found")
    if path.profile is None or path.profile.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your roadmap")

    step = db.scalar(
        select(CareerPathStep).where(
            CareerPathStep.id == step_id,
            CareerPathStep.path_id == path_id,
        )
    )
    if step is None:
        raise HTTPException(status_code=404, detail="Step not found")

    if step.done_at is None:
        step.done_at = datetime.now(timezone.utc)

    steps = list(path.steps)
    done = sum(1 for s in steps if s.done_at is not None)
    if steps and done == len(steps):
        path.status = PathStatus.COMPLETED
    db.commit()
    db.refresh(step)

    return StepCompleteResponse(
        step_id=step.id,
        path_id=path_id,
        seq=step.seq,
        done_at=step.done_at,
        path_status=path.status.value if hasattr(path.status, "value") else str(path.status),
        steps_done=done,
        steps_total=len(steps),
    )
