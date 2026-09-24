"""Preferences API (plan §18): GET/PATCH /preferences — §16 exposure.

GET returns the current 8-component weight bars (effective vs. global),
recent learned changes, and leaned skill affinities.  PATCH {reset: true}
deletes the learned state (w_u + skill_affinities) back to defaults.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.db import get_db
from app.models.profile import Profile
from app.models.user import User
from app.services import personalization

router = APIRouter(prefix="/preferences", tags=["preferences"])


class WeightBar(BaseModel):
    component: str
    label: str
    weight: float
    global_weight: float


class HistoryEntry(BaseModel):
    component: str
    delta: float
    weight: float
    reason: str
    at: str


class AffinityEntry(BaseModel):
    skill: str
    score: float


class PreferenceState(BaseModel):
    weights: list[WeightBar]
    n_events: int
    shrinkage: float
    updated_at: str | None = None
    history: list[HistoryEntry] = []
    affinities: list[AffinityEntry] = []
    personalization_note: str | None = None


class PreferencesUpdate(BaseModel):
    reset: bool = Field(default=False, description="Delete learned weights + affinities")


def _profile_id(db: Session, user_id) -> Any:
    return db.scalar(select(Profile.id).where(Profile.user_id == user_id))


@router.get("", response_model=PreferenceState, summary="Read learned M4 weights")
def read_preferences(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> PreferenceState:
    """Settings → 'Your preferences': weight bars + recent changes (§16)."""
    return PreferenceState.model_validate(
        personalization.summary(db, current_user.id, _profile_id(db, current_user.id))
    )


@router.patch("", response_model=PreferenceState, summary="Reset learned weights")
def update_preferences(
    payload: PreferencesUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> PreferenceState:
    """Reset to defaults: deletes w_u (system_config m4:*) + skill_affinities."""
    if not payload.reset:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only {reset: true} is supported.",
        )
    personalization.reset(db, current_user.id, _profile_id(db, current_user.id))
    db.commit()
    return PreferenceState.model_validate(
        personalization.summary(db, current_user.id, None)
    )
