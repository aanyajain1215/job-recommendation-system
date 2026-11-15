"""Operational and online-learning monitoring endpoints (admin-guarded)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin_user
from app.core.db import get_db
from app.models.feedback import Feedback
from app.models.interaction import Interaction
from app.models.ops import LlmUsage, ModelRegistry
from app.models.recommendation import Recommendation
from app.models.user import User
from app.services import bandit

router = APIRouter(prefix="/monitoring", tags=["monitoring"])


@router.get("/summary")
def monitoring_summary(
    _: Annotated[User, Depends(get_current_admin_user)],
    db: Annotated[Session, Depends(get_db)],
    days: int = 7,
) -> dict[str, Any]:
    since = datetime.now(timezone.utc) - timedelta(days=max(1, min(days, 90)))

    recs = db.scalar(select(func.count()).select_from(Recommendation).where(Recommendation.served_at >= since)) or 0
    interactions = db.scalar(select(func.count()).select_from(Interaction).where(Interaction.created_at >= since)) or 0
    feedback = db.scalar(select(func.count()).select_from(Feedback).where(Feedback.created_at >= since)) or 0

    # bandit/exploration stats from snapshots
    bandit_served = 0
    prop_sum = 0.0
    rec_rows = db.scalars(select(Recommendation).where(Recommendation.served_at >= since).limit(5000)).all()
    for r in rec_rows:
        snap = r.snapshot or {}
        if snap.get("bandit"):
            bandit_served += 1
            prop_sum += float(snap.get("propensity") or 0.0)

    # simple outcome rates
    events = db.execute(
        select(Interaction.event_type, func.count())
        .where(Interaction.created_at >= since)
        .group_by(Interaction.event_type)
    ).all()
    event_counts = {str(k.value if hasattr(k, "value") else k): int(v) for k, v in events}

    # LLM usage
    llm_rows = db.execute(
        select(func.count(), func.coalesce(func.sum(LlmUsage.prompt_tokens + LlmUsage.completion_tokens), 0), func.coalesce(func.avg(LlmUsage.latency_ms), 0), func.coalesce(func.sum(func.cast(LlmUsage.flagged, type_=func.count().type)), 0))
        .where(LlmUsage.created_at >= since)
    ).one()
    # flagged count robustly
    flagged = db.scalar(select(func.count()).select_from(LlmUsage).where(LlmUsage.created_at >= since, LlmUsage.flagged.is_(True))) or 0

    models = db.scalars(select(ModelRegistry).order_by(ModelRegistry.name, ModelRegistry.created_at.desc())).all()
    model_state = [
        {"name": m.name, "version": m.version, "active": m.active, "artifact_path": m.artifact_path, "metrics": m.metrics}
        for m in models
    ]

    policy = bandit.get_policy()
    return {
        "window_days": days,
        "recommendations_served": int(recs),
        "interactions": int(interactions),
        "feedback": int(feedback),
        "events": event_counts,
        "bandit": {
            "served_explorations": bandit_served,
            "avg_propensity": round(prop_sum / bandit_served, 6) if bandit_served else None,
            "policy_model_version": policy.model_version,
            "online_updates": policy.updates,
            "artifact_present": bandit.latest_artifact_path() is not None,
        },
        "llm": {
            "calls": int(llm_rows[0] or 0),
            "tokens": int(llm_rows[1] or 0),
            "avg_latency_ms": round(float(llm_rows[2] or 0), 2),
            "flagged_calls": int(flagged),
        },
        "models": model_state,
    }