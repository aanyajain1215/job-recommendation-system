"""M5 — Bradley-Terry cold-start elicitation (plan §6 M5, §19 /onboarding).

Three pairwise "which job would you prefer?" choices at onboarding → a
Bradley-Terry style fit over the 8 scoring-component axes → the user's
*initial* weight vector before any feedback history exists.

Model (deterministic, no LLM, no network):

    P(prefer A) = σ( w · (shape_A − shape_B) )       σ = logistic

with ``w`` fitted by L2-regularised gradient ascent on the logistic
log-likelihood in softmax space (w = softmax(θ)), initialised at the global
weights and pulled back toward them (λ=1.0).  Three observations over eight
axes is deliberately underdetermined — the regulariser keeps the result a
*modest, honest tilt* of the defaults rather than a confident overfit.
Fallback when the user skips onboarding: the global weights (§6 M5).

Storage: ``system_config`` row ``m5:{user_id}`` (same pattern as M4).
``personalization.base_weights`` reads it so the feed, Settings bars and M4
bounds all adopt the elicited baseline.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.ops import SystemConfig
from app.services.runtime_config import validate_weights
from app.services.scoring import DEFAULT_WEIGHTS

COMPONENTS: list[str] = list(DEFAULT_WEIGHTS)

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

# Learning hyperparameters — fixed constants, unit-tested for determinism.
FIT_ITERATIONS = 600
FIT_LEARNING_RATE = 0.5
FIT_L2 = 1.0
FIT_FLOOR = 1e-4

# ---------------------------------------------------------------------------
# The three pairwise questions (deterministic shapes in [0, 1] per component)
# ---------------------------------------------------------------------------

PAIRS: list[dict[str, Any]] = [
    {
        "index": 0,
        "question": "Which role would you rather take next month?",
        "a": {
            "label": "Senior Backend Engineer — fintech, high pay, on-site",
            "blurb": "Excellent salary band, heavy production Go/Postgres load.",
            "shape": {
                "semantic": 0.55, "skill": 0.85, "experience": 0.90,
                "education": 0.55, "project": 0.50, "location": 0.35,
                "salary": 0.95, "interest": 0.55,
            },
        },
        "b": {
            "label": "Developer Advocate — remote, mission-driven NGO",
            "blurb": "Modest pay, fully remote, broad content + community work.",
            "shape": {
                "semantic": 0.75, "skill": 0.45, "experience": 0.50,
                "education": 0.55, "project": 0.65, "location": 0.95,
                "salary": 0.30, "interest": 0.80,
            },
        },
    },
    {
        "index": 1,
        "question": "Your learning budget is one course. Where does it go?",
        "a": {
            "label": "Deep ML specialisation — models, maths, research papers",
            "blurb": "Hard prerequisite stack: PyTorch, linear algebra, MLOps.",
            "shape": {
                "semantic": 0.95, "skill": 0.95, "experience": 0.75,
                "education": 0.85, "project": 0.55, "location": 0.50,
                "salary": 0.65, "interest": 0.70,
            },
        },
        "b": {
            "label": "Full-stack product craft — ship UI, APIs, tests",
            "blurb": "Broader shipping skills with immediate project evidence.",
            "shape": {
                "semantic": 0.55, "skill": 0.65, "experience": 0.60,
                "education": 0.45, "project": 0.95, "location": 0.55,
                "salary": 0.60, "interest": 0.60,
            },
        },
    },
    {
        "index": 2,
        "question": "Two offers, same team. What breaks the tie?",
        "a": {
            "label": "Hybrid, 3 days home — close to family",
            "blurb": "Commute and place matter more than title prestige.",
            "shape": {
                "semantic": 0.50, "skill": 0.55, "experience": 0.55,
                "education": 0.50, "project": 0.50, "location": 0.95,
                "salary": 0.55, "interest": 0.55,
            },
        },
        "b": {
            "label": "Requires a master's degree on paper",
            "blurb": "Formal credentials are actually screened for here.",
            "shape": {
                "semantic": 0.60, "skill": 0.70, "experience": 0.65,
                "education": 0.95, "project": 0.50, "location": 0.45,
                "salary": 0.65, "interest": 0.55,
            },
        },
    },
]


def _key(user_id: UUID | str) -> str:
    return f"m5:{user_id}"


def pairs_payload() -> dict[str, Any]:
    """GET /onboarding/pairs — the fixed question set + component glossary."""
    return {
        "pairs": PAIRS,
        "components": [
            {"component": c, "label": COMPONENT_LABELS[c]} for c in COMPONENTS
        ],
        "note": (
            "Three quick picks set your starting weights (Bradley-Terry, plan §6 M5). "
            "You can skip — defaults apply — and feedback later refines them."
        ),
    }


# ---------------------------------------------------------------------------
# Fit (deterministic regularised logistic regression in softmax space)
# ---------------------------------------------------------------------------

def _sigmoid(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    ex = math.exp(x)
    return ex / (1.0 + ex)


def fit_weights(
    choices: list[dict[str, Any]],
    *,
    iterations: int = FIT_ITERATIONS,
    learning_rate: float = FIT_LEARNING_RATE,
    l2: float = FIT_L2,
) -> dict[str, float]:
    """Fit w from ``[{shape_a, shape_b, chosen: "a"|"b"}, …]`` → Σw = 1.

    Deterministic: fixed init at global weights, fixed iteration count.
    """
    theta = [math.log(max(DEFAULT_WEIGHTS[c], FIT_FLOOR)) for c in COMPONENTS]
    theta0 = list(theta)

    # Pre-compute feature deltas per observation
    obs: list[tuple[list[float], float]] = []
    for row in choices:
        a, b = row["shape_a"], row["shape_b"]
        delta = [float(a.get(c, 0.5)) - float(b.get(c, 0.5)) for c in COMPONENTS]
        y = 1.0 if str(row.get("chosen", "a")).lower() == "a" else 0.0
        obs.append((delta, y))
    if not obs:
        return _normalised(theta)

    for _ in range(iterations):
        # Gradient ASCENT on loglik − (λ/2)‖θ−θ0‖²: the L2 term pulls θ
        # back toward the global prior (adding +λ(θ−θ0) would repel and
        # diverge, collapsing softmax weights to exact 0.0 via underflow).
        grad = [-l2 * (theta[i] - theta0[i]) for i in range(len(theta))]
        for delta, y in obs:
            dot = sum(theta[i] * delta[i] for i in range(len(theta)))
            err = y - _sigmoid(dot)
            for i in range(len(theta)):
                grad[i] += err * delta[i]
        for i in range(len(theta)):
            theta[i] += learning_rate * grad[i] / len(obs)

    return _normalised(theta)


def _normalised(theta: list[float]) -> dict[str, float]:
    m = max(theta)
    exps = [math.exp(t - m) for t in theta]
    total = sum(exps) or 1.0
    raw = {c: exps[i] / total for i, c in enumerate(COMPONENTS)}
    return validate_weights(raw)


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def save(
    db: Session,
    user_id: UUID | str,
    weights: dict[str, float],
    choices: list[dict[str, Any]],
    target_family: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "weights": weights,
        "n_choices": len(choices),
        "target_family": target_family,
        "origin": "m5_bradley_terry",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    row = db.get(SystemConfig, _key(user_id))
    if row is None:
        db.add(
            SystemConfig(
                key=_key(user_id),
                value=payload,
                description="M5 elicited initial weights (plan §6)",
            )
        )
    else:
        row.value = payload
    return payload


def load_raw(db: Session, user_id: UUID | str) -> dict[str, Any] | None:
    row = db.get(SystemConfig, _key(user_id))
    if row is None or not isinstance(row.value, dict):
        return None
    return dict(row.value)


def load_weights(db: Session, user_id: UUID | str) -> dict[str, float] | None:
    """Validated elicited weights, or None (skip / corrupt → defaults)."""
    state = load_raw(db, user_id)
    if state is None:
        return None
    try:
        return validate_weights(state.get("weights"))
    except ValueError:
        return None


def reset(db: Session, user_id: UUID | str) -> None:
    row = db.get(SystemConfig, _key(user_id))
    if row is not None:
        db.delete(row)
