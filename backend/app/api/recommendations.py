from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_current_user
from app.core.db import get_db
from app.models.profile import Profile
from app.models.recommendation import Recommendation
from app.models.skill import ProfileSkill
from app.models.user import User
from app.schemas.recommendation import RecommendationFeedResponse
from app.services import personalization
from app.services.recommender import ContentRecommender, generate_candidates

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
        # If user has no profile record at all, create a minimal blank one for them
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
    # The commit also flushes any embedding cache-fills computed above.
    try:
        for item in feed.items:
            db.add(
                Recommendation(
                    profile_id=profile.id,
                    job_id=item.job.id,
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
                    },
                    strategy=feed.recommendation_type,
                    model_version=item.model_version,
                    propensity=item.propensity,
                )
            )
        db.commit()
    except Exception:
        db.rollback()

    return feed
