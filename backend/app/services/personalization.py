"""M4 preference-learner — bounded, partial-pooling personalization (plan §16).

Deterministic online model: no LLM, no network, no black box.
- Component weight vector ``w_u`` over the 8 score components, stored per user
  in ``system_config`` under key ``m4:{user_id}``.
- Per-skill affinity rows in ``skill_affinities`` with 30-day half-life decay.

Update rule (§16): multiplicative update toward the component profile of the
liked vs. disliked item, learning rate η=0.15, bounds [0.5, 2.0] × global
weights, renormalised to Σ=1.  Cold users shrink toward the global weights
with the empirical-Bayes factor n/(n+10).  Skill affinities lean the
SkillMatch component via ``max(0, 1 + affinity·0.3)`` — never full removal.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.feedback import SkillAffinity
from app.models.job import Job
from app.models.ops import SystemConfig
from app.models.profile import Profile
from app.models.recommendation import Recommendation
from app.models.skill import Skill
from app.services.scoring import DEFAULT_WEIGHTS

# --- hyperparameters (plan §16 — deterministic, documented) -----------------
LEARNING_RATE = 0.15
BOUND_LO = 0.5                 # w_u ∈ [0.5, 2.0] × w_global before renorm
BOUND_HI = 2.0
SHRINKAGE_K = 10               # shrinkage n/(n+k): new users ≈ global weights
HISTORY_LIMIT = 20             # recent learned changes kept for Settings
AFFINITY_CLAMP = 1.0           # affinity ∈ [-1, 1]
AFFINITY_HALF_LIFE_DAYS = 30.0
AFFINITY_STEP_NEG = -0.25      # too_difficult / not_interested / not_relevant
AFFINITY_STEP_POS = 0.2        # relevant / save / apply

POSITIVE_REASONS = {"relevant"}
NEGATIVE_WEIGHT_REASONS = {
    "not_relevant", "not_interested", "too_difficult",
    "salary_issue", "location_issue",
}
# reasons that never inform component weights (not preference signals)
WEIGHT_SKIP_REASONS = {"already_applied", "other"}
# skill-lean signals: only skill-related reasons lean affinities
AFFINITY_NEG_REASONS = {"not_relevant", "not_interested", "too_difficult"}

COMPONENT_LABELS: dict[str, str] = {
    "semantic": "Semantic",
    "skill": "Skill",
    "experience": "Experience",
    "education": "Education",
    "project": "Project",
    "location": "Location",
    "salary": "Salary",
    "interest": "Career-interest",
}

NOTE_DEVIATION_MIN = 0.004     # don't narrate sub-0.4% weight wobble


def _key(user_id: UUID | str) -> str:
    return f"m4:{user_id}"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def global_weights(db: Session | None = None) -> dict[str, float]:
    """Global weight vector (plan §7 precedence: code defaults → system_config).

    With no ``db`` this is exactly ``DEFAULT_WEIGHTS``; with a session the
    admin override from ``PUT /admin/config`` is applied when present.
    """
    if db is None:
        return dict(DEFAULT_WEIGHTS)
    from app.services import runtime_config

    return runtime_config.get_scoring_weights(db)


def base_weights(db: Session, user_id: UUID | str) -> dict[str, float]:
    """M5-aware baseline for one user: elicited Bradley-Terry weights when the
    user completed onboarding, else the global vector (§6 M5 fallback)."""
    g = global_weights(db)
    from app.services import elicitation

    elicited = elicitation.load_weights(db, user_id)
    if elicited:
        g = dict(elicited)
    return g


# ---------------------------------------------------------------------------
# State I/O (system_config JSONB)
# ---------------------------------------------------------------------------

def load_state(db: Session, user_id: UUID | str) -> dict[str, Any] | None:
    row = db.get(SystemConfig, _key(user_id))
    if row is None or not isinstance(row.value, dict):
        return None
    return dict(row.value)


def _save_state(db: Session, user_id: UUID | str, state: dict[str, Any]) -> None:
    row = db.get(SystemConfig, _key(user_id))
    if row is None:
        row = SystemConfig(
            key=_key(user_id),
            value=state,
            description="M4 learned component weights (plan §16)",
        )
        db.add(row)
        # Sessions run with autoflush=False — flush now so the next
        # load_state() in this session sees the row instead of re-adding
        # a duplicate primary key (system_config_pkey violation).
        db.flush()
    else:
        row.value = state


# ---------------------------------------------------------------------------
# Effective weights (partial pooling + honest note)
# ---------------------------------------------------------------------------

def _shrinkage(n_events: float) -> float:
    n = max(0.0, float(n_events))
    return n / (n + SHRINKAGE_K) if n > 0 else 0.0


def _note_for(
    weights: dict[str, float],
    n_events: float,
    g: dict[str, float],
) -> str | None:
    """Personalization note for the feed (§16) — largest real deviation only."""
    if n_events <= 0:
        return None
    deltas = sorted(
        ((k, weights.get(k, 0.0) - g.get(k, 0.0)) for k in weights),
        key=lambda t: -abs(t[1]),
    )
    if not deltas or abs(deltas[0][1]) < NOTE_DEVIATION_MIN:
        return None
    comp, _delta = deltas[0]
    verb = "raised" if deltas[0][1] > 0 else "lowered"
    label = COMPONENT_LABELS.get(comp, comp.capitalize())
    return (
        f"{label} weight {verb} to {weights[comp]:.3f} "
        "because of your recent feedback."
    )


def effective_weights(
    db: Session,
    user_id: UUID | str,
) -> tuple[dict[str, float], str | None, float]:
    """(weights, personalization_note, shrinkage) — empirical-Bayes blend."""
    g = base_weights(db, user_id)
    state = load_state(db, user_id)
    if state is None:
        return g, None, 0.0

    learned = state.get("weights") or {}
    n_events = float(state.get("n_events", 0) or 0)
    shrink = _shrinkage(n_events)

    blended: dict[str, float] = {}
    for k, gk in g.items():
        try:
            uk = float(learned.get(k, gk))
        except (TypeError, ValueError):
            uk = gk
        blended[k] = shrink * uk + (1.0 - shrink) * gk

    total = sum(blended.values()) or 1.0
    weights = {k: v / total for k, v in blended.items()}
    return weights, _note_for(weights, n_events, g), shrink


# ---------------------------------------------------------------------------
# Weight update (multiplicative, bounded, renormalised)
# ---------------------------------------------------------------------------

def _snapshot_components(
    db: Session,
    profile: Profile,
    job: Job,
) -> dict[str, float] | None:
    """Latest served component breakdown for (profile, job) — engine truth."""
    rec = db.scalar(
        select(Recommendation)
        .where(
            Recommendation.profile_id == profile.id,
            Recommendation.job_id == job.id,
        )
        .order_by(Recommendation.served_at.desc())
        .limit(1)
    )
    if rec is None or not isinstance(rec.snapshot, dict):
        return None
    comps = rec.snapshot.get("components")
    if not isinstance(comps, dict) or not comps:
        return None
    return comps


def update_weights(
    db: Session,
    profile: Profile,
    job: Job,
    reason: str,
) -> None:
    """One bounded multiplicative step toward/away from this item's shape."""
    comps = _snapshot_components(db, profile, job)
    if not comps:
        return

    sign = 1.0 if reason in POSITIVE_REASONS else -1.0
    g = base_weights(db, profile.user_id)
    state = load_state(db, profile.user_id) or {}
    learned = state.get("weights") or {}
    current: dict[str, float] = {}
    for k, gk in g.items():
        try:
            current[k] = float(learned.get(k, gk))
        except (TypeError, ValueError):
            current[k] = gk

    # component values in [0, 1]; missing components read as neutral 0.5
    values = {
        k: max(0.0, min(100.0, float(comps.get(k, 50.0)))) / 100.0
        for k in g
    }
    mean = sum(values.values()) / len(values) if values else 0.5

    updated: dict[str, float] = {}
    for k, wk in current.items():
        dev = values[k] - mean
        candidate = wk * math.exp(sign * LEARNING_RATE * dev)
        lo, hi = BOUND_LO * g[k], BOUND_HI * g[k]
        updated[k] = min(hi, max(lo, candidate))

    total = sum(updated.values()) or 1.0
    updated = {k: v / total for k, v in updated.items()}

    now = _utcnow()
    history = list(state.get("history") or [])
    moves = sorted(
        ((k, updated[k] - current[k]) for k in updated),
        key=lambda t: -abs(t[1]),
    )
    for comp, delta in moves[:3]:
        if abs(delta) < 1e-6:
            continue
        history.append(
            {
                "component": comp,
                "delta": round(delta, 5),
                "weight": round(updated[comp], 5),
                "reason": reason,
                "at": _iso(now),
            }
        )

    _save_state(
        db,
        profile.user_id,
        {
            "weights": updated,
            "n_events": int(state.get("n_events", 0) or 0) + 1,
            "history": history[-HISTORY_LIMIT:],
            "updated_at": _iso(now),
        },
    )


# ---------------------------------------------------------------------------
# Skill affinities (decay-on-read, clamped, never removal)
# ---------------------------------------------------------------------------

def decay(
    score: float,
    updated_at: datetime | None,
    now: datetime | None = None,
    half_life_days: float = AFFINITY_HALF_LIFE_DAYS,
) -> float:
    """Half-life decay applied lazily on every read/write (§16)."""
    if updated_at is None:
        return score
    now = now or _utcnow()
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=timezone.utc)
    days = max(0.0, (now - updated_at).total_seconds() / 86400.0)
    hl = max(1.0, float(half_life_days or AFFINITY_HALF_LIFE_DAYS))
    return score * (0.5 ** (days / hl))


def _lean_reason(reason: str) -> float | None:
    """Affinity step for a feedback/interaction reason; None = no lean."""
    if reason in POSITIVE_REASONS:
        return AFFINITY_STEP_POS
    if reason in AFFINITY_NEG_REASONS:
        return AFFINITY_STEP_NEG
    return None


def update_affinities(
    db: Session,
    profile: Profile,
    job: Job,
    reason: str,
) -> None:
    """Lean this job's *required* skills (§16: never blind removal)."""
    step = _lean_reason(str(reason).lower())
    if step is None:
        return
    req_skills = [
        js.skill
        for js in (job.skills or [])
        if js.is_required and js.skill is not None
    ]
    if not req_skills:
        return

    now = _utcnow()
    for skill in req_skills:
        row = db.get(
            SkillAffinity,
            {"profile_id": profile.id, "skill_id": skill.id},
        )
        if row is None:
            row = SkillAffinity(
                profile_id=profile.id,
                skill_id=skill.id,
                score=0.0,
                half_life_days=AFFINITY_HALF_LIFE_DAYS,
                updated_at=now,
            )
            db.add(row)
            # autoflush=False: flush immediately so the next call's db.get()
            # finds this row rather than inserting a duplicate composite key.
            db.flush()
        base = decay(row.score, row.updated_at, now, row.half_life_days)
        row.score = max(-AFFINITY_CLAMP, min(AFFINITY_CLAMP, base + step))
        row.updated_at = now


def load_affinities(db: Session, profile_id: UUID) -> dict[str, float]:
    """canonical lowercase skill name -> decayed affinity (|v| >= 0.01)."""
    rows = db.execute(
        select(SkillAffinity, Skill.name)
        .join(Skill, Skill.id == SkillAffinity.skill_id)
        .where(SkillAffinity.profile_id == profile_id)
    ).all()
    now = _utcnow()
    out: dict[str, float] = {}
    for row, name in rows:
        value = decay(row.score, row.updated_at, now, row.half_life_days)
        if abs(value) >= 0.01:
            out[name.lower().strip()] = round(value, 4)
    return out


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

def apply_feedback(
    db: Session,
    profile: Profile,
    job: Job,
    reason: str,
) -> str | None:
    """Full M4 update for one explicit feedback event; returns the note."""
    reason = str(reason).lower()
    if reason not in WEIGHT_SKIP_REASONS:
        update_weights(db, profile, job, reason)
    update_affinities(db, profile, job, reason)
    weights, note, _shrink = effective_weights(db, profile.user_id)
    return note if reason not in WEIGHT_SKIP_REASONS else note


def apply_interaction(
    db: Session,
    user_id: UUID,
    job_id: UUID,
    event_type: str,
) -> None:
    """Affinity-only update for implicit events (save/apply/dismiss)."""
    ev = str(getattr(event_type, "value", event_type)).lower()
    if ev in ("save", "apply"):
        lean = "relevant"
    elif ev == "dismiss":
        lean = "not_interested"
    else:
        return
    profile = db.scalar(select(Profile).where(Profile.user_id == user_id))
    job = db.get(Job, job_id)
    if profile is None or job is None:
        return
    update_affinities(db, profile, job, lean)


def reset(db: Session, user_id: UUID | str, profile_id: UUID | None) -> None:
    """Settings → 'Reset to defaults': delete w_u + skill_affinities (§16)."""
    row = db.get(SystemConfig, _key(user_id))
    if row is not None:
        db.delete(row)
    if profile_id is not None:
        db.execute(
            delete(SkillAffinity).where(SkillAffinity.profile_id == profile_id)
        )


def summary(
    db: Session,
    user_id: UUID | str,
    profile_id: UUID | None,
) -> dict[str, Any]:
    """Settings → 'Your preferences': weight bars + recent changes (§16)."""
    g = base_weights(db, user_id)
    weights, note, shrink = effective_weights(db, user_id)
    state = load_state(db, user_id) or {}

    bars = [
        {
            "component": k,
            "label": COMPONENT_LABELS.get(k, k.capitalize()),
            "weight": round(weights.get(k, g[k]), 4),
            "global_weight": round(g[k], 4),
        }
        for k in g
    ]

    affinities: list[dict[str, Any]] = []
    if profile_id is not None:
        affinities = sorted(
            (
                {"skill": name, "score": score}
                for name, score in load_affinities(db, profile_id).items()
            ),
            key=lambda a: -abs(a["score"]),
        )

    return {
        "weights": bars,
        "n_events": int(state.get("n_events", 0) or 0),
        "shrinkage": round(float(shrink), 3),
        "updated_at": state.get("updated_at"),
        "history": list(state.get("history") or []),
        "affinities": affinities,
        "personalization_note": note,
    }
