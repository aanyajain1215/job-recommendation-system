"""What-If Simulator endpoints (plan §18):
    POST /simulate        — run a mutation, persist the Simulation row
    GET  /simulations     — the seeker's past runs

The simulator scores a shadow profile only — profile rows are never
mutated (plan §10 invariant), and runs are idempotent: the same mutation
twice produces byte-identical deltas.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.gap import load_profile
from app.core.db import get_db
from app.models.enums import ProficiencyLevel, WorkMode
from app.models.simulation import Simulation
from app.models.user import User
from app.services.recommender import generate_candidates
from app.services.simulator import simulate

router = APIRouter(tags=["simulator"])


# ---------------------------------------------------------------------------
# Mutation schema (plan §10)
# ---------------------------------------------------------------------------

class SkillMutation(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    level: ProficiencyLevel = ProficiencyLevel.INTERMEDIATE
    years: float | None = Field(default=None, ge=0, le=50)


class SalaryMutation(BaseModel):
    min: int | None = Field(default=None, ge=0)
    max: int | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, max_length=3)


class ProjectMutation(BaseModel):
    name: str = ""
    description: str = ""
    skills: list[str] = Field(default_factory=list)


class SimulateRequest(BaseModel):
    add_skills: list[SkillMutation] = Field(default_factory=list)
    remove_skills: list[str] = Field(default_factory=list)
    expected_salary: SalaryMutation | None = None
    location: str | None = Field(default=None, max_length=120)
    work_mode: WorkMode | None = None
    target_family: str | None = Field(default=None, max_length=100)
    add_project: ProjectMutation | None = None
    add_cert: dict[str, Any] | None = None
    target_job_id: UUID | None = None


class SimulateResponse(BaseModel):
    id: UUID | None = None
    mutation: dict[str, Any]
    result_delta: dict[str, Any]


class SimulationListItem(BaseModel):
    id: UUID
    mutation: dict[str, Any]
    result_delta: dict[str, Any]
    created_at: datetime


class SimulationListResponse(BaseModel):
    items: list[SimulationListItem]
    total: int


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/simulate", response_model=SimulateResponse)
def run_simulation(
    body: SimulateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> SimulateResponse:
    """Mutation in → score deltas out (plan §10).  Scores the top-100
    baseline candidates from candidate generation; persists the run."""
    profile = load_profile(db, current_user.id)
    candidates = generate_candidates(db, profile, limit=200)

    mutation = body.model_dump(mode="json", exclude={"target_job_id"})
    result_delta = simulate(
        profile,
        candidates,
        mutation,
        target_job_id=body.target_job_id,
    )

    row = Simulation(
        profile_id=profile.id,
        mutation=mutation,
        result_delta=result_delta,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    return SimulateResponse(
        id=row.id,
        mutation=mutation,
        result_delta=result_delta,
    )


@router.get("/simulations", response_model=SimulationListResponse)
def list_simulations(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> SimulationListResponse:
    """Recent simulation runs for the current seeker (plan §18)."""
    profile = load_profile(db, current_user.id)
    rows = db.scalars(
        select(Simulation)
        .where(Simulation.profile_id == profile.id)
        .order_by(Simulation.created_at.desc(), Simulation.id.desc())
        .limit(limit)
    ).all()
    total = (
        db.scalar(
            select(func.count())
            .select_from(Simulation)
            .where(Simulation.profile_id == profile.id)
        )
        or 0
    )

    return SimulationListResponse(
        items=[
            SimulationListItem(
                id=r.id,
                mutation=r.mutation,
                result_delta=r.result_delta,
                created_at=r.created_at,
            )
            for r in rows
        ],
        total=total,
    )
