"""Feedback capture (plan §18): POST /feedback — the §16 loop's entry point.

Persists the 7-reason feedback row and runs the deterministic M4 update
(component weights + skill affinities).  The response echoes the
``personalization_note`` so the UI can show what the model learned.
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
from app.models.skill import JobSkill, ProfileSkill
from app.models.user import User
from app.services import personalization

router = APIRouter(tags=["feedback"])


class FeedbackCreate(BaseModel):
    job_id: UUID
    reason: FeedbackReason
    note: str | None = Field(default=None, max_length=2000)


class FeedbackResponse(BaseModel):
    id: UUID
    job_id: UUID
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

    The LLM is never involved: weights move by the bounded multiplicative
    rule and skill affinities lean via the §16 step constants.
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
    entry = Feedback(
        profile_id=profile.id,
        job_id=job.id,
        reason=payload.reason,
        note=(payload.note or "").strip() or None,
    )
    db.add(entry)

    personalization_note = personalization.apply_feedback(
        db, profile, job, payload.reason.value
    )
    db.commit()
    db.refresh(entry)

    return FeedbackResponse(
        id=entry.id,
        job_id=entry.job_id,
        reason=entry.reason,
        note=entry.note,
        created_at=entry.created_at,
        personalization_note=personalization_note,
    )
