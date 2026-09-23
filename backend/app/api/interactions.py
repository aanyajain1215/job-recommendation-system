"""
Interaction logging API.

POST /interactions  — fire-and-forget event recording (202 Accepted).
GET  /interactions/me — last 100 interactions for the calling user.
"""
from __future__ import annotations

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.db import SessionLocal, get_db
from app.models.interaction import Interaction
from app.models.job import Job
from app.models.user import User
from app.schemas.interaction import InteractionCreate, InteractionResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/interactions", tags=["interactions"])


# ---------------------------------------------------------------------------
# Background worker — runs AFTER the 202 response is sent
# ---------------------------------------------------------------------------

def _persist_interaction(
    user_id: UUID,
    job_id: UUID,
    event_type: str,
    metadata: dict | None,
) -> None:
    """Opens a fresh DB session and inserts the interaction row.

    Runs in the FastAPI background-task thread pool; never blocks the request path.
    """
    db: Session = SessionLocal()
    try:
        row = Interaction(
            user_id=user_id,
            job_id=job_id,
            event_type=event_type,
            metadata_=metadata,
        )
        db.add(row)
        db.commit()
        logger.debug("Interaction logged: user=%s job=%s type=%s", user_id, job_id, event_type)
    except Exception:
        db.rollback()
        logger.exception(
            "Failed to persist interaction: user=%s job=%s type=%s",
            user_id, job_id, event_type,
        )
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Log a user–job interaction event (async)",
    response_description="Event accepted for processing",
)
def log_interaction(
    payload: InteractionCreate,
    background_tasks: BackgroundTasks,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """Accept an interaction event and persist it asynchronously.

    The caller receives **202 Accepted** immediately; the DB write happens
    in a background task after the response is sent.

    The authenticated user's ID is taken from the JWT — the `user_id` field
    in the payload is validated against it to prevent spoofing.
    """
    # Guard: caller may only log events for themselves
    if payload.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You may only log interactions for your own account.",
        )

    # Verify the job exists (lightweight check — no eager loads needed)
    job_exists = db.scalar(select(Job.id).where(Job.id == payload.job_id))
    if job_exists is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {payload.job_id} not found.",
        )

    background_tasks.add_task(
        _persist_interaction,
        user_id=payload.user_id,
        job_id=payload.job_id,
        event_type=payload.event_type,
        metadata=payload.metadata,
    )

    return {
        "status": "accepted",
        "message": "Interaction event queued for logging.",
        "event_type": payload.event_type,
    }


@router.get(
    "/me",
    response_model=list[InteractionResponse],
    summary="Retrieve your recent interactions",
)
def get_my_interactions(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    limit: int = 100,
) -> list[InteractionResponse]:
    """Return the calling user's most recent interaction records (newest first).

    Useful for the frontend to deduplicate events and render optimistic UI.
    """
    rows = db.scalars(
        select(Interaction)
        .where(Interaction.user_id == current_user.id)
        .order_by(Interaction.created_at.desc())
        .limit(min(limit, 500))
    ).all()

    return [
        InteractionResponse(
            id=r.id,
            user_id=r.user_id,
            job_id=r.job_id,
            event_type=r.event_type,
            metadata=r.metadata_,
            created_at=r.created_at,
        )
        for r in rows
    ]
