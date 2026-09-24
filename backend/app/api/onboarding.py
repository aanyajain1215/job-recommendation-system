"""M5 onboarding elicitation routes (plan §6 M5, §19 /onboarding).

Skip-able: the frontend offers these three pairwise choices right after
registration; skipping leaves the global weights untouched (deterministic
fallback).  The fit itself lives in ``services/elicitation`` — no LLM.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.db import get_db
from app.models.job_family import JobFamily
from app.models.profile import Profile
from app.models.user import User
from app.services import elicitation

router = APIRouter(prefix="/onboarding", tags=["onboarding"])


class OnboardChoice(BaseModel):
    pair_index: int = Field(ge=0, le=2)
    chosen: str = Field(pattern="^[ab]$")


class OnboardingCompleteRequest(BaseModel):
    choices: list[OnboardChoice]
    target_family: str | None = None


@router.get("/pairs")
def get_onboarding_pairs() -> dict[str, Any]:
    """The three fixed pairwise questions + component glossary (deterministic)."""
    return elicitation.pairs_payload()


@router.post("/complete")
def complete_onboarding(
    payload: OnboardingCompleteRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """Fit Bradley-Terry weights from the three choices and store the initial
    user weight vector (§6 M5).  Also sets the profile's target family when
    provided (powers CareerInterestMatch from the very first feed)."""
    indexes = [c.pair_index for c in payload.choices]
    if sorted(indexes) != [0, 1, 2] or len(set(indexes)) != 3:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide exactly one choice for each pair (indexes 0, 1, 2).",
        )

    choices = []
    for choice in payload.choices:
        pair = elicitation.PAIRS[choice.pair_index]
        choices.append(
            {
                "shape_a": pair["a"]["shape"],
                "shape_b": pair["b"]["shape"],
                "chosen": choice.chosen,
            }
        )

    weights = elicitation.fit_weights(choices)

    family_name: str | None = None
    profile = db.scalar(select(Profile).where(Profile.user_id == current_user.id))
    if payload.target_family and profile is not None:
        family = db.scalar(
            select(JobFamily).where(
                func.lower(JobFamily.name) == payload.target_family.strip().lower()
            )
        )
        if family is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Unknown target family '{payload.target_family}'.",
            )
        profile.target_job_family_id = family.id
        family_name = family.name

    elicitation.save(
        db,
        current_user.id,
        weights,
        [c.model_dump() for c in payload.choices],
        family_name,
    )
    db.commit()

    return {
        "weights": [
            {
                "component": component,
                "label": dict(elicitation.COMPONENT_LABELS).get(
                    component, component.capitalize()
                ),
                "weight": round(value, 4),
            }
            for component, value in weights.items()
        ],
        "target_family": family_name,
        "message": (
            "Initial weights saved from your three choices (Bradley-Terry). "
            "Feedback will refine them further — reset any time in Settings."
        ),
    }
