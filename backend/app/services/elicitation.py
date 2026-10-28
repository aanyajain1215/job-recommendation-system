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


# ---------------------------------------------------------------------------
# Adaptive onboarding — a larger question bank with 3 options per question
# ---------------------------------------------------------------------------
#
# The original three pairwise questions (``PAIRS`` above) are kept byte-for-byte
# so the legacy Bradley-Terry fit and its unit-tests are untouched.  This bank
# powers the *adaptive* flow: 8 questions, each offering **three** roles instead
# of two.  The next question shown to the user is chosen by
# ``select_next_question`` — the one that best discriminates between the
# remaining hypotheses under the user's current weight estimate.
#
# Questions 0–2 deliberately mirror ``PAIRS`` (same a/b shapes) with a third
# option added, so an adaptive session that happens to draw them still probes
# the same axes as the legacy flow.

ADAPTIVE_POOL = 8
MIN_QUESTIONS = 3          # below this the fit is under-determined → prior
MAX_QUESTIONS = 6          # diminishing returns past this; user may stop early
COVERAGE_BONUS = 0.25      # weight of the under-probed-component term

QUESTION_BANK: list[dict[str, Any]] = [
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
        "c": {
            "label": "ML Engineer — model platform, hybrid",
            "blurb": "Train and ship models on a shared platform team.",
            "shape": {
                "semantic": 0.95, "skill": 0.95, "experience": 0.70,
                "education": 0.65, "project": 0.70, "location": 0.55,
                "salary": 0.70, "interest": 0.75,
            },
        },
    },
    {
        "index": 1,
        "question": "Your learning budget is one course. Where does it go?",
        "a": {
            "label": "Deep ML specialisation — models, maths, research",
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
        "c": {
            "label": "Data engineering — pipelines, warehouses, orchestration",
            "blurb": "Move and model data at scale; strong systems grounding.",
            "shape": {
                "semantic": 0.60, "skill": 0.85, "experience": 0.75,
                "education": 0.55, "project": 0.70, "location": 0.55,
                "salary": 0.70, "interest": 0.60,
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
        "c": {
            "label": "Bigger title, wider scope — lead the squad",
            "blurb": "Seniority and ownership outweigh comfort and credentials.",
            "shape": {
                "semantic": 0.60, "skill": 0.80, "experience": 0.95,
                "education": 0.50, "project": 0.65, "location": 0.45,
                "salary": 0.75, "interest": 0.65,
            },
        },
    },
    {
        "index": 3,
        "question": "It's 6 PM and you're still heads-down. Why?",
        "a": {
            "label": "A genuinely hard model problem won't let go",
            "blurb": "Chasing a research-grade ML question past office hours.",
            "shape": {
                "semantic": 0.95, "skill": 0.90, "experience": 0.65,
                "education": 0.70, "project": 0.55, "location": 0.50,
                "salary": 0.55, "interest": 0.70,
            },
        },
        "b": {
            "label": "Shipping a release users see tomorrow",
            "blurb": "Cutting a feature live beats polishing internals.",
            "shape": {
                "semantic": 0.55, "skill": 0.70, "experience": 0.75,
                "education": 0.45, "project": 0.95, "location": 0.50,
                "salary": 0.60, "interest": 0.65,
            },
        },
        "c": {
            "label": "Unblocking and mentoring the rest of the team",
            "blurb": "Lifting others compounds further than solo output.",
            "shape": {
                "semantic": 0.55, "skill": 0.65, "experience": 0.85,
                "education": 0.65, "project": 0.60, "location": 0.55,
                "salary": 0.60, "interest": 0.85,
            },
        },
    },
    {
        "index": 4,
        "question": "Pick the shape of your next twelve months.",
        "a": {
            "label": "Become the ML-infra specialist on the team",
            "blurb": "Depth over breadth — own the training/serving stack.",
            "shape": {
                "semantic": 0.90, "skill": 0.95, "experience": 0.80,
                "education": 0.60, "project": 0.60, "location": 0.50,
                "salary": 0.70, "interest": 0.65,
            },
        },
        "b": {
            "label": "Own a product feature end to end",
            "blurb": "Design, build, launch, and answer for the numbers.",
            "shape": {
                "semantic": 0.55, "skill": 0.70, "experience": 0.85,
                "education": 0.45, "project": 0.95, "location": 0.55,
                "salary": 0.65, "interest": 0.70,
            },
        },
        "c": {
            "label": "Join a 5-person startup wearing every hat",
            "blurb": "Wide scope, high ambiguity, real ownership.",
            "shape": {
                "semantic": 0.60, "skill": 0.75, "experience": 0.80,
                "education": 0.40, "project": 0.85, "location": 0.60,
                "salary": 0.55, "interest": 0.85,
            },
        },
    },
    {
        "index": 5,
        "question": "Which failure would sting the most?",
        "a": {
            "label": "The model silently failed to generalise",
            "blurb": "Great offline metrics, wrong in the real world.",
            "shape": {
                "semantic": 0.95, "skill": 0.85, "experience": 0.65,
                "education": 0.70, "project": 0.50, "location": 0.50,
                "salary": 0.55, "interest": 0.70,
            },
        },
        "b": {
            "label": "Your service broke in prod at 2 AM",
            "blurb": "Reliability and operations are on you.",
            "shape": {
                "semantic": 0.55, "skill": 0.80, "experience": 0.85,
                "education": 0.45, "project": 0.70, "location": 0.50,
                "salary": 0.65, "interest": 0.60,
            },
        },
        "c": {
            "label": "Users churned because the flow confused them",
            "blurb": "The product missed the mark, not the code.",
            "shape": {
                "semantic": 0.65, "skill": 0.60, "experience": 0.70,
                "education": 0.45, "project": 0.85, "location": 0.55,
                "salary": 0.55, "interest": 0.80,
            },
        },
    },
    {
        "index": 6,
        "question": "Your ideal team looks like…",
        "a": {
            "label": "A research lab that publishes",
            "blurb": "Papers, novelty, and academic collaboration.",
            "shape": {
                "semantic": 0.95, "skill": 0.85, "experience": 0.60,
                "education": 0.85, "project": 0.50, "location": 0.50,
                "salary": 0.55, "interest": 0.70,
            },
        },
        "b": {
            "label": "A large org with deep specialisation",
            "blurb": "Scale, strong mentors, clear ladders.",
            "shape": {
                "semantic": 0.60, "skill": 0.85, "experience": 0.80,
                "education": 0.60, "project": 0.60, "location": 0.55,
                "salary": 0.80, "interest": 0.60,
            },
        },
        "c": {
            "label": "A small startup with wide scope",
            "blurb": "Everyone touches everything; titles are thin.",
            "shape": {
                "semantic": 0.55, "skill": 0.70, "experience": 0.75,
                "education": 0.40, "project": 0.90, "location": 0.60,
                "salary": 0.55, "interest": 0.85,
            },
        },
    },
    {
        "index": 7,
        "question": "How should your next role compensate you?",
        "a": {
            "label": "+40% cash now, even if learning slows",
            "blurb": "Take the money; grow on your own time.",
            "shape": {
                "semantic": 0.50, "skill": 0.55, "experience": 0.70,
                "education": 0.45, "project": 0.55, "location": 0.55,
                "salary": 0.95, "interest": 0.50,
            },
        },
        "b": {
            "label": "+40% learning now, pay can wait",
            "blurb": "Invest in trajectory; cash follows later.",
            "shape": {
                "semantic": 0.90, "skill": 0.90, "experience": 0.75,
                "education": 0.70, "project": 0.65, "location": 0.50,
                "salary": 0.35, "interest": 0.75,
            },
        },
        "c": {
            "label": "Equity-heavy, low cash, big upside",
            "blurb": "Bet on the company; smooth the salary curve.",
            "shape": {
                "semantic": 0.55, "skill": 0.65, "experience": 0.70,
                "education": 0.40, "project": 0.75, "location": 0.55,
                "salary": 0.45, "interest": 0.85,
            },
        },
    },
]

# Which option keys each question exposes (a/b for the legacy pairs, a/b/c here)
_OPTION_KEYS = ("a", "b", "c")

BANK_BY_INDEX: dict[int, dict[str, Any]] = {q["index"]: q for q in QUESTION_BANK}


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
# Adaptive flow: multi-option fit + adaptive question selection
# ---------------------------------------------------------------------------

def fit_weights_multioption(
    answers: list[dict[str, Any]],
    *,
    iterations: int = FIT_ITERATIONS,
    learning_rate: float = FIT_LEARNING_RATE,
    l2: float = FIT_L2,
) -> dict[str, float]:
    """Plackett-Luce fit over k-way choices → Σw = 1.

    ``answers`` = ``[{"shapes": [shape1, shape2, …], "chosen": 0}, …]`` where
    ``chosen`` is the index of the picked option.  Each shape is a dict of
    component → value in [0, 1].  For two options this reduces exactly to the
    Bradley-Terry logistic in :func:`fit_weights`; with three it is the standard
    Plackett-Luce / softmax likelihood:

        P(chosen = i) = exp(w·s_i) / Σ_j exp(w·s_j)

    Gradient ASCENT on loglik − (λ/2)‖θ−θ0‖², same fixed init and iteration
    count as the binary fit, so it is equally deterministic.
    """
    theta = [math.log(max(DEFAULT_WEIGHTS[c], FIT_FLOOR)) for c in COMPONENTS]
    theta0 = list(theta)

    obs: list[tuple[list[list[float]], int]] = []
    for row in answers:
        shapes = row["shapes"]
        chosen = int(row["chosen"])
        vecs = [
            [float(s.get(c, 0.5)) for c in COMPONENTS] for s in shapes
        ]
        obs.append((vecs, chosen))
    if not obs:
        return _normalised(theta)

    for _ in range(iterations):
        grad = [-l2 * (theta[i] - theta0[i]) for i in range(len(theta))]
        for vecs, chosen in obs:
            dots = [sum(theta[i] * v[i] for i in range(len(theta))) for v in vecs]
            m = max(dots)
            exps = [math.exp(d - m) for d in dots]
            total = sum(exps) or 1.0
            probs = [e / total for e in exps]
            # d log P(chosen) / d theta = s_chosen − Σ_j p_j s_j
            for i in range(len(theta)):
                signal = vecs[chosen][i] - sum(
                    probs[j] * vecs[j][i] for j in range(len(vecs))
                )
                grad[i] += signal
        for i in range(len(theta)):
            theta[i] += learning_rate * grad[i] / len(obs)

    return _normalised(theta)


def _softmax_over_options(
    theta: list[float], shapes: list[dict[str, Any]]
) -> list[float]:
    """P(pick each option) under the current weights — the adaptive selector's
    belief about how the user will answer."""
    dots = [
        sum(theta[i] * float(s.get(c, 0.5)) for i, c in enumerate(COMPONENTS))
        for s in shapes
    ]
    m = max(dots)
    exps = [math.exp(d - m) for d in dots]
    total = sum(exps) or 1.0
    return [e / total for e in exps]


def _entropy(probs: list[float]) -> float:
    h = 0.0
    for p in probs:
        if p > 0:
            h -= p * math.log(p)
    return h


def _shapes_of(q: dict[str, Any]) -> list[dict[str, Any]]:
    return [q[k]["shape"] for k in _OPTION_KEYS if k in q]


def _coverage_spread(q: dict[str, Any]) -> list[float]:
    """Per-component spread across the question's options — how much asking it
    would tell us about each axis."""
    shapes = _shapes_of(q)
    spread = []
    for c in COMPONENTS:
        vals = [float(s.get(c, 0.5)) for s in shapes]
        spread.append(max(vals) - min(vals))
    return spread


def current_theta(answers: list[dict[str, Any]] | None = None) -> list[float]:
    """θ = log of the current weight estimate (prior until evidence arrives).

    Accepts lightweight answers (``{"index", "chosen"}``) — shapes are resolved
    from the bank — so callers need not carry the full option shapes around.
    """
    answers = answers or []
    rows = _as_fit_rows(answers)
    if not rows:
        return [math.log(max(DEFAULT_WEIGHTS[c], FIT_FLOOR)) for c in COMPONENTS]
    w = fit_weights_multioption(rows)
    return [math.log(max(w[c], FIT_FLOOR)) for c in COMPONENTS]


def _as_fit_rows(answers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalise answers to fit rows: ``{"shapes": [...], "chosen": idx}``.

    Answers that already carry ``shapes`` are passed through; otherwise the
    shapes are looked up from the bank by ``index``.  Rows that can't be
    resolved (unknown index / bad option) are dropped rather than raising —
    the selector must never crash on stale client state.
    """
    rows: list[dict[str, Any]] = []
    for a in answers:
        if "shapes" in a:
            rows.append({"shapes": a["shapes"], "chosen": int(a["chosen"])})
            continue
        q = BANK_BY_INDEX.get(int(a.get("index", -1)))
        if q is None:
            continue
        keys = [k for k in _OPTION_KEYS if k in q]
        ch = str(a.get("chosen", "a")).lower()
        if ch not in keys:
            continue
        rows.append({"shapes": [q[k]["shape"] for k in keys], "chosen": keys.index(ch)})
    return rows


def select_next_question(
    answers: list[dict[str, Any]] | None = None,
    *,
    asked: set[int] | None = None,
) -> dict[str, Any] | None:
    """Pick the most informative unanswered question (deterministic).

    Score = entropy of the predicted answer distribution (how close the current
    weights are to a coin-flip between the options = maximum discrimination)
    + a coverage bonus that favours questions probing components the user has
    not yet been asked about.  No randomness: same answers → same question.
    """
    answers = answers or []
    asked = asked or {int(a.get("index", -1)) for a in answers}
    theta = current_theta(answers)

    # components already probed by answered questions (sum of option spreads)
    probed = [0.0] * len(COMPONENTS)
    for a in answers:
        q = BANK_BY_INDEX.get(int(a.get("index", -1)))
        if q is not None:
            for i, s in enumerate(_coverage_spread(q)):
                probed[i] += s

    best, best_score = None, -1.0
    for q in QUESTION_BANK:
        if q["index"] in asked:
            continue
        shapes = _shapes_of(q)
        ent = _entropy(_softmax_over_options(theta, shapes))
        spread = _coverage_spread(q)
        # reward probing components that are still unprobed
        unprobed = sum(spread[i] * (1.0 - min(probed[i], 1.0))
                       for i in range(len(COMPONENTS)))
        score = ent + COVERAGE_BONUS * unprobed / len(COMPONENTS)
        # strict > keeps the lowest index on ties → fully deterministic
        if score > best_score:
            best, best_score = q, score

    return best


def adaptive_payload(answers: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """GET /onboarding/flow — the adaptive session's opening state.

    Returns the bank metadata plus the first question to show.  The client keeps
    calling :func:`select_next_question` (via ``/onboarding/next``) after each
    answer; nothing is persisted until ``/onboarding/complete``.
    """
    answers = answers or []
    nxt = select_next_question(answers)
    asked = {int(a.get("index", -1)) for a in answers}
    remaining = [q for q in QUESTION_BANK if q["index"] not in asked]
    rows = _as_fit_rows(answers)
    preview = fit_weights_multioption(rows) if rows else dict(DEFAULT_WEIGHTS)
    return {
        "question": nxt,
        "components": [
            {"component": c, "label": COMPONENT_LABELS[c]} for c in COMPONENTS
        ],
        "preview_weights": [
            {"component": c, "label": COMPONENT_LABELS[c], "weight": preview[c]}
            for c in COMPONENTS
        ],
        "answered": len(answers),
        "remaining": len(remaining),
        "min_questions": MIN_QUESTIONS,
        "max_questions": MAX_QUESTIONS,
        "note": (
            "Answer at least {min} — the next question is picked to reduce your "
            "biggest remaining uncertainty, and updates your weights live."
        ).format(min=MIN_QUESTIONS),
    }



# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def save(
    db: Session,
    user_id: UUID | str,
    weights: dict[str, float],
    choices: list[dict[str, Any]],
    target_family: str | None = None,
    origin: str = "m5_bradley_terry",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "weights": weights,
        "n_choices": len(choices),
        "target_family": target_family,
        "origin": origin,
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
