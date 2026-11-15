from typing import Annotated
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_current_user
from app.core.db import get_db
from app.models.enums import RecommendationEventType
from app.models.profile import Profile
from app.models.recommendation import Recommendation, RecommendationEvent
from app.models.skill import ProfileSkill
from app.models.user import User
from app.schemas.recommendation import (
    RecommendationEventCreate,
    RecommendationEventOut,
    RecommendationFeedResponse,
)
from app.services import live_jobs, personalization
from app.services.recommender import ContentRecommender, generate_candidates

log = logging.getLogger(__name__)

router = APIRouter(prefix="/recommendations", tags=["recommendations"])


@router.get("", response_model=RecommendationFeedResponse)
def get_recommendation_feed(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> RecommendationFeedResponse:
    """Personalized recommendation feed (plan §4, §23 Phase 1).

    Pipeline (deterministic core — the LLM never assigns scores or SQL):
    1. Candidate generation — pgvector KNN ∪ Postgres FTS ∪ skill overlap,
       fused with Reciprocal Rank Fusion (`generate_candidates`).
    2. Deterministic 8-component scoring (`scoring.score_pair`).
    3. Strategy re-rank (`rerank.rerank` — deterministic until M2 ships).
    4. MMR diversity + per-family caps + one deterministic exploration slot.
    5. §12 explanation contract per item.
    6. Snapshot persistence for the offline evaluation loop (plan §3).
    7. RecommendationEvent recording (SERVED) with exact recommendation_id.
    """
    # 1. Fetch user's profile with eager-loaded skills
    profile = db.scalar(
        select(Profile)
        .where(Profile.user_id == current_user.id)
        .options(
            selectinload(Profile.skills).selectinload(ProfileSkill.skill),
        )
    )

    if not profile:
        profile = Profile(
            user_id=current_user.id,
            first_name=current_user.email.split("@")[0].capitalize(),
            last_name="",
        )
        db.add(profile)
        db.commit()
        db.refresh(profile)

    # 2. Hybrid candidate generation (KNN ∪ FTS ∪ skill → RRF), fully eager-loaded
    candidates = generate_candidates(db, profile, limit)

    # 2b. Live leg — real-time Adzuna results for the profile's own text.
    try:
        live_candidates = live_jobs.live_candidates(db, profile, limit)
    except Exception:  # noqa: BLE001 - live leg is best-effort
        log.exception("live candidate leg failed; serving platform-only feed")
        live_candidates = []
    if live_candidates:
        candidates = list(candidates) + live_candidates

    # 3. Score → rerank → diversify → explain (M4 weights/affinities, §16)
    weights, m4_note, _shrink = personalization.effective_weights(
        db, profile.user_id
    )
    affinities = personalization.load_affinities(db, profile.id)
    feed = ContentRecommender.recommend_jobs(
        profile=profile,
        jobs=candidates,
        limit=limit,
        weights=weights,
        affinities=affinities,
        personalization_note=m4_note,
    )

    # 4. Persist what was served — snapshot carries component breakdown +
    # explanation contract; best-effort so bookkeeping never fails a feed.
    try:
        for rank_idx, item in enumerate(feed.items, start=1):
            if item.job.source == "adzuna":
                continue
            rec = Recommendation(
                profile_id=profile.id,
                job_id=UUID(item.job.id),
                snapshot={
                    "match_score": item.match_score,
                    "components": item.explanation.components
                    if item.explanation
                    else None,
                    "contributions": item.explanation.contributions
                    if item.explanation
                    else None,
                    "readiness": item.readiness.model_dump()
                    if item.readiness
                    else None,
                    "rank_strategy": item.strategy,
                    "model_version": item.model_version,
                    "propensity": item.propensity,
                    "recommendation_type": feed.recommendation_type,
                    "request_limit": limit,
                    "bandit": getattr(item, "bandit", None),
                },
                strategy=feed.recommendation_type,
                model_version=item.model_version,
                propensity=item.propensity,
            )
            db.add(rec)
            db.flush()
            item.recommendation_id = rec.id

            # Record SERVED lifecycle event
            event = RecommendationEvent(
                recommendation_id=rec.id,
                profile_id=profile.id,
                event_type=RecommendationEventType.SERVED,
                rank=rank_idx,
            )
            db.add(event)
        db.commit()
    except Exception:
        db.rollback()

    return feed


@router.post(
    "/events",
    response_model=RecommendationEventOut,
    status_code=status.HTTP_201_CREATED,
    summary="Record explicit recommendation lifecycle event (impression, click, dismiss, etc.)",
)
def record_recommendation_event(
    payload: RecommendationEventCreate,
    response: Response,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> RecommendationEventOut:
    """Explicitly records client-side lifecycle events (e.g. card IMPRESSION, CLICKED, DISMISSED).

    Guarantees:
    - User ownership validation (cannot report events for other profiles' recommendations).
    - Idempotency: duplicate submissions for (recommendation_id, event_type) return existing event with 200 OK.
    """
    profile = db.scalar(select(Profile).where(Profile.user_id == current_user.id))
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Profile not found for current user.",
        )

    rec = db.get(Recommendation, payload.recommendation_id)
    if not rec:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Recommendation record not found.",
        )

    if rec.profile_id != profile.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not own this recommendation.",
        )

    # Idempotent check
    existing = db.scalar(
        select(RecommendationEvent).where(
            RecommendationEvent.recommendation_id == payload.recommendation_id,
            RecommendationEvent.event_type == payload.event_type,
        )
    )
    if existing:
        response.status_code = status.HTTP_200_OK
        return RecommendationEventOut(
            id=existing.id,
            recommendation_id=existing.recommendation_id,
            profile_id=existing.profile_id,
            event_type=existing.event_type,
            occurred_at=existing.occurred_at,
            rank=existing.rank,
            request_id=existing.request_id,
            metadata=existing.metadata_,
        )

    event = RecommendationEvent(
        recommendation_id=rec.id,
        profile_id=profile.id,
        event_type=payload.event_type,
        rank=payload.rank,
        request_id=payload.request_id,
        metadata_=payload.metadata,
    )
    db.add(event)
    db.commit()
    db.refresh(event)

    return RecommendationEventOut(
        id=event.id,
        recommendation_id=event.recommendation_id,
        profile_id=event.profile_id,
        event_type=event.event_type,
        occurred_at=event.occurred_at,
        rank=event.rank,
        request_id=event.request_id,
        metadata=event.metadata_,
    )


@router.get(
    "/events",
    response_model=list[RecommendationEventOut],
    summary="List recommendation events for the current user's profile",
)
def list_my_recommendation_events(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    event_type: Annotated[RecommendationEventType | None, Query()] = None,
) -> list[RecommendationEventOut]:
    """Retrieve logged recommendation events for the caller's profile with bounded pagination."""
    profile = db.scalar(select(Profile).where(Profile.user_id == current_user.id))
    if not profile:
        return []

    stmt = (
        select(RecommendationEvent)
        .where(RecommendationEvent.profile_id == profile.id)
        .order_by(RecommendationEvent.occurred_at.desc())
        .limit(limit)
    )
    if event_type:
        stmt = stmt.where(RecommendationEvent.event_type == event_type)

    events = db.scalars(stmt).all()
    return [
        RecommendationEventOut(
            id=e.id,
            recommendation_id=e.recommendation_id,
            profile_id=e.profile_id,
            event_type=e.event_type,
            occurred_at=e.occurred_at,
            rank=e.rank,
            request_id=e.request_id,
            metadata=e.metadata_,
        )
        for e in events
    ]
