"""Feedback capture (plan §18): POST /feedback — the §16 loop's entry point.

Persists the 7-reason feedback row, associates it with the exact recommendation
snapshot when provided, and runs the deterministic M4 update (component weights + skill affinities).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_current_user
from app.core.db import get_db
from app.models.enums import FeedbackReason
from app.models.feedback import Feedback
from app.models.job import Job
from app.models.profile import Profile
from app.models.recommendation import Recommendation
from app.models.skill import JobSkill, ProfileSkill
from app.models.user import User
from app.services import personalization

router = APIRouter(tags=["feedback"])


class FeedbackCreate(BaseModel):
    job_id: UUID
    reason: FeedbackReason
    recommendation_id: UUID | None = Field(
        default=None,
        description="Optional recommendation ID linking this feedback to its exact algorithm snapshot.",
    )
    note: str | None = Field(default=None, max_length=2000)


class FeedbackResponse(BaseModel):
    id: UUID
    job_id: UUID
    recommendation_id: UUID | None = None
    reason: FeedbackReason
    note: str | None = None
    created_at: datetime | None = None
    personalization_note: str | None = None


def _get_or_create_profile(db: Session, user: User) -> Profile:
    profile = db.scalar(
        select(Profile)
        .where(Profile.user_id == user.id)
        .options(
            selectinload(Profile.skills).selectinload(ProfileSkill.skill),
        )
    )
    if profile is None:
        profile = Profile(
            user_id=user.id,
            first_name=user.email.split("@")[0].capitalize(),
            last_name="",
        )
        db.add(profile)
        db.flush()
    return profile


@router.post(
    "/feedback",
    response_model=FeedbackResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Capture recommendation feedback (7 reasons + free note)",
)
def create_feedback(
    payload: FeedbackCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> FeedbackResponse:
    """Explicit feedback → row + deterministic M4 update (plan §16).

    Guarantees:
    - If recommendation_id is provided, verifies it belongs to the current user's profile and matches the job.
    - If recommendation_id is omitted, records direct feedback (backward compatible).
    - Prevents cross-tenant spoofing.
    """
    job = db.scalar(
        select(Job)
        .where(Job.id == payload.job_id)
        .options(
            selectinload(Job.skills).selectinload(JobSkill.skill),
        )
    )
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    profile = _get_or_create_profile(db, current_user)

    # Validate exact recommendation context if provided
    rec_id: UUID | None = None
    if payload.recommendation_id:
        rec = db.get(Recommendation, payload.recommendation_id)
        if rec is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Referenced recommendation record not found.",
            )
        if rec.profile_id != profile.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Recommendation does not belong to your profile.",
            )
        if rec.job_id != job.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Recommendation context mismatch: recommendation job does not match target job.",
            )
        rec_id = rec.id

    entry = Feedback(
        profile_id=profile.id,
        job_id=job.id,
        recommendation_id=rec_id,
        reason=payload.reason,
        note=(payload.note or "").strip() or None,
    )
    db.add(entry)

    personalization_note = personalization.apply_feedback(
        db, profile, job, payload.reason.value
    )

    # RL/bandit online update from explicit feedback (best-effort)
    try:
        from app.services import bandit

        reward = bandit.reward_for_reason(payload.reason.value)
        if reward is not None:
            bandit.apply_online_reward(db, profile.id, job.id, reward)
    except Exception:
        pass

    db.commit()
    db.refresh(entry)

    return FeedbackResponse(
        id=entry.id,
        job_id=entry.job_id,
        recommendation_id=entry.recommendation_id,
        reason=entry.reason,
        note=entry.note,
        created_at=entry.created_at,
        personalization_note=personalization_note,
    )
