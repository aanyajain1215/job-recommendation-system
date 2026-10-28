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


class AdaptiveAnswer(BaseModel):
    """One answered adaptive question: which bank index, and which option."""

    index: int = Field(ge=0)
    chosen: str = Field(pattern="^[abc]$")


class OnboardingCompleteRequest(BaseModel):
    # Legacy three-pair flow (kept for the original contract + tests).
    choices: list[OnboardChoice] | None = None
    # Adaptive multi-question flow: send the bank answers instead.
    answers: list[AdaptiveAnswer] | None = None
    target_family: str | None = None


@router.get("/pairs")
def get_onboarding_pairs() -> dict[str, Any]:
    """The three fixed pairwise questions + component glossary (deterministic)."""
    return elicitation.pairs_payload()


@router.get("/flow")
def get_onboarding_flow() -> dict[str, Any]:
    """Adaptive onboarding: first question + live weight preview shell."""
    return elicitation.adaptive_payload([])


@router.post("/next")
def next_onboarding_question(
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Given the answers so far, return the next (most informative) question and
    an updated weight preview.  Stateless — the client holds the answers."""
    raw = payload.get("answers") or []
    answers: list[dict[str, Any]] = []
    for a in raw:
        try:
            idx = int(a["index"])
        except (KeyError, TypeError, ValueError):
            continue
        if idx not in elicitation.BANK_BY_INDEX:
            continue
        ch = str(a.get("chosen", "a")).lower()
        if ch not in ("a", "b", "c"):
            continue
        answers.append({"index": idx, "chosen": ch})
    return elicitation.adaptive_payload(answers)


@router.post("/complete")
def complete_onboarding(
    payload: OnboardingCompleteRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """Fit weights and store the initial user weight vector (§6 M5).

    Accepts either the legacy three ``choices`` or the adaptive ``answers``.
    Also sets the profile's target family when provided (powers
    CareerInterestMatch from the very first feed)."""
    origin = "m5_bradley_terry"
    message = (
        "Initial weights saved from your three choices (Bradley-Terry). "
        "Feedback will refine them further — reset any time in Settings."
    )

    if payload.answers:
        # ---- adaptive multi-option flow ----
        answers = []
        for a in payload.answers:
            q = elicitation.BANK_BY_INDEX.get(a.index)
            if q is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Unknown question index {a.index}.",
                )
            keys = [k for k in ("a", "b", "c") if k in q]
            if a.chosen not in keys:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Question {a.index} has no option '{a.chosen}'.",
                )
            answers.append(
                {
                    "index": a.index,
                    "chosen": a.chosen,
                    "shapes": [q[k]["shape"] for k in keys],
                    "chosen_idx": keys.index(a.chosen),
                }
            )
        if len(answers) < elicitation.MIN_QUESTIONS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Answer at least {elicitation.MIN_QUESTIONS} questions "
                    "before setting your weights."
                ),
            )
        shapes_answers = [
            {"shapes": a["shapes"], "chosen": a["chosen_idx"]} for a in answers
        ]
        weights = elicitation.fit_weights_multioption(shapes_answers)
        origin = "m5_adaptive_plackett_luce"
        message = (
            f"Initial weights saved from your {len(answers)} picks (adaptive, "
            "Plackett-Luce). Feedback will refine them further — reset in Settings."
        )
        stored = [
            {"index": a["index"], "chosen": a["chosen"]} for a in answers
        ]
    else:
        # ---- legacy three-pair flow ----
        if not payload.choices:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Provide either 'choices' (legacy) or 'answers' (adaptive).",
            )
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
        stored = [c.model_dump() for c in payload.choices]

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
        stored,
        family_name,
        origin=origin,
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
        "message": message,
    }
