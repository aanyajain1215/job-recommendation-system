"""Ranklet strategy dispatch + the M2 feature builder (plan §6/§17).

Three strategies, selected by settings.recommender_strategy:

- deterministic — pure component weights (default; always available)
- ltr_blend     — 0.35·LightGBM LambdaRank (M2) + deterministic, Δ clamped ±15
- ltr_full      — LightGBM score only

The M2 model is optional: if the artifact, its feature manifest, or lightgbm
is missing/mismatched, every strategy silently degrades to `deterministic`
and reports the effective strategy so the API/UI never lies about what
produced the ranking.  The LLM never participates — all numbers come from
scoring.py or the trained artifact.

`build_features` produces the 30-feature deterministic vector used for
training *and* serving; every sub-signal is derived from explicit
ComponentInputs or logged FeatureContext values (no lookups, no I/O), so
train/serve skew is impossible by construction.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.core.config import get_settings
from app.services.scoring import (
    EXPERIENCE_LEVEL_RANGES,
    ComponentInputs,
    ScoreResult,
    education_rank,
)

log = logging.getLogger(__name__)

ARTIFACT_DIR = Path(__file__).resolve().parents[2] / "ml" / "artifacts"
# plan §6/§17: ltr_blend uses α=0.35, contribution clamped to ±15 points
LGBM_BLEND_WEIGHT = 0.35
LGBM_MAX_DELTA = 15.0

# The M2 feature vector (plan §6):8 component scores + sub-signals.
# Order is pinned by the artifact manifest — a mismatch degrades to
# deterministic rather than silently feeding the wrong columns.
FEATURE_ORDER = [
    "semantic",
    "skill",
    "experience",
    "education",
    "project",
    "location",
    "salary",
    "interest",
    "required_coverage",
    "preferred_coverage",
    "missing_required_count",
    "semantic_cosine_raw",
    "experience_gap_years",
    "education_rank_delta",
    "salary_iou",
    "location_class",
    "family_match",
    "job_age_days",
    "applicant_count",
    "profile_completeness",
    "historical_apply_rate",
    "exploration_flag",
    "seeker_skill_count",
    "job_skill_count",
    "transfer_credit_count",
    "partial_credit_count",
    "salary_disclosed",
    "is_remote",
    "experience_level_ordinal",
    "project_overlap_count",
]

_LEVEL_ORDER = ["entry", "mid", "senior", "lead", "executive"]

# Neutral fill for legacy callers that only have a ScoreResult (deterministic
# defaults matching the plan §6 neutral priors).
_NEUTRAL_TAIL = [
    0.5,    # required_coverage
    0.5,    # preferred_coverage
    0.0,    # missing_required_count
    0.0,    # semantic_cosine_raw
    0.0,    # experience_gap_years
    0.0,    # education_rank_delta
    0.5,    # salary_iou (undisclosed prior)
    1.0,    # location_class
    0.0,    # family_match
    0.0,    # job_age_days
    0.0,    # applicant_count
    0.0,    # profile_completeness
    0.0,    # historical_apply_rate
    0.0,    # exploration_flag
    0.0,    # seeker_skill_count
    0.0,    # job_skill_count
    0.0,    # transfer_credit_count
    0.0,    # partial_credit_count
    0.0,    # salary_disclosed
    0.0,    # is_remote
    1.0,    # experience_level_ordinal (mid)
    0.0,    # project_overlap_count
]


@dataclass
class FeatureContext:
    """Per-(profile, job) extras the pure scorer doesn't own (plan §6 M2).

    Everything here is deterministic and logged; defaults keep the vector
    well-formed when a caller has no context (legacy/direct tests).
    """

    job_age_days: float = 0.0
    applicant_count: float = 0.0
    profile_completeness: float = 0.0
    historical_apply_rate: float = 0.0
    exploration_flag: float = 0.0


@dataclass
class RankOutcome:
    """Final score + which strategy actually produced it."""

    final: float
    strategy: str          # "deterministic" | "ltr_blend" | "ltr_full"
    model_version: str | None = None
    delta_note: str | None = None  # present only when LTR moved the score

    @property
    def used_ltr(self) -> bool:
        return self.strategy in ("ltr_blend", "ltr_full")


# ---------------------------------------------------------------------------
# Feature build (plan §6 M2 — identical at train and serve time)
# ---------------------------------------------------------------------------

def build_features(
    inputs: ComponentInputs,
    result: ScoreResult,
    ctx: FeatureContext | None = None,
) -> list[float]:
    """30-feature deterministic vector:8 components + logged sub-signals."""
    ctx = ctx or FeatureContext()
    comp = result.components
    possessed = inputs.seeker_skills
    transfers = inputs.transfer_similarities
    required = [r for r in inputs.job_skills if r.is_required]
    preferred = [r for r in inputs.job_skills if not r.is_required]

    def _coverage(reqs: list) -> float:
        if not reqs:
            return 1.0          # neutral: job states no bar of this kind
        hit = 0
        for r in reqs:
            key = r.name.lower().strip()
            if key in possessed or key in transfers:
                hit += 1
        return round(hit / len(reqs), 4)

    cosine = inputs.semantic_cosine if inputs.semantic_cosine is not None else 0.0

    low, high = EXPERIENCE_LEVEL_RANGES.get(inputs.job_level, (0.0, 10.0))
    years = inputs.years_of_experience
    if years is None:
        exp_gap = 0.0
    elif years < low:
        exp_gap = round(years - low, 2)
    elif years > high:
        exp_gap = round(years - high, 2)
    else:
        exp_gap = 0.0

    rank_user = education_rank(inputs.seeker_degree)
    rank_req = education_rank(inputs.job_degree)
    edu_delta = (
        float(rank_user - rank_req)
        if (rank_user is not None and rank_req is not None)
        else 0.0
    )

    if None in (inputs.seeker_salary_min, inputs.job_salary_min):
        salary_iou = 0.5        # undisclosed prior (plan §6)
    else:
        s_low = float(inputs.seeker_salary_min)
        s_high = float(inputs.seeker_salary_max or inputs.seeker_salary_min)
        j_low = float(inputs.job_salary_min)
        j_high = float(inputs.job_salary_max or inputs.job_salary_min)
        inter = max(0.0, min(s_high, j_high) - max(s_low, j_low))
        union = max(s_high, j_high) - min(s_low, j_low)
        salary_iou = round(inter / union, 4) if union > 0 else 1.0

    if inputs.job_is_remote:
        loc_class = 3.0
    else:
        seeker = (inputs.seeker_location or "").strip().lower()
        job = (inputs.job_location or "").strip().lower()
        preferred_locs = {p.lower().strip() for p in inputs.seeker_preferred_locations}
        if (seeker and job and seeker == job) or (job and job in preferred_locs):
            loc_class = 2.0
        elif (
            seeker
            and job
            and seeker.split(",")[-1].strip()
            == job.split(",")[-1].strip()
        ):
            loc_class = 1.0
        elif inputs.seeker_open_to_remote:
            loc_class = 0.5
        else:
            loc_class = 0.0

    family_match = 0.0
    if inputs.seeker_target_family and inputs.job_family:
        if inputs.seeker_target_family.strip().lower() == inputs.job_family.strip().lower():
            family_match = 1.0
        elif inputs.family_graph_distance is not None and inputs.family_graph_distance <= 1:
            family_match = 0.5

    job_names = {r.name.lower().strip() for r in inputs.job_skills}
    project_overlap = float(
        len({s.lower().strip() for s in inputs.seeker_project_skills} & job_names)
    )

    vector = [
        float(comp.get("semantic", 0.0)),
        float(comp.get("skill", 0.0)),
        float(comp.get("experience", 0.0)),
        float(comp.get("education", 0.0)),
        float(comp.get("project", 0.0)),
        float(comp.get("location", 0.0)),
        float(comp.get("salary", 0.0)),
        float(comp.get("interest", 0.0)),
        _coverage(required),
        _coverage(preferred),
        float(len(result.skill_detail.missing_required)),
        round(float(cosine), 4),
        exp_gap,
        edu_delta,
        salary_iou,
        loc_class,
        family_match,
        float(ctx.job_age_days),
        float(ctx.applicant_count),
        float(ctx.profile_completeness),
        float(ctx.historical_apply_rate),
        float(ctx.exploration_flag),
        float(len(possessed)),
        float(len(inputs.job_skills)),
        float(len(result.skill_detail.transferable)),
        float(len(result.skill_detail.partial)),
        1.0 if inputs.job_salary_min is not None else 0.0,
        1.0 if inputs.job_is_remote else 0.0,
        float(_LEVEL_ORDER.index(inputs.job_level.value))
        if inputs.job_level.value in _LEVEL_ORDER
        else 1.0,
        project_overlap,
    ]
    assert len(vector) == len(FEATURE_ORDER), "feature vector drifted from manifest"
    return vector


def component_vector(result: ScoreResult) -> list[float]:
    """Legacy path: components + neutral tail (deterministic, no context)."""
    head = [float(result.components.get(name, 0.0)) for name in FEATURE_ORDER[:8]]
    return head + list(_NEUTRAL_TAIL)


# ---------------------------------------------------------------------------
# Artifact loading (manifest-validated)
# ---------------------------------------------------------------------------

@lru_cache
def _load_lgbm():
    """Load the active ranklet artifact.

    Returns (booster, version, feature_order) — feature_order is None when no
    manifest sidecar exists (pre-manifest artifacts).  Any load problem,
    including a manifest/FEATURE_ORDER mismatch, yields (None, None, None) so
    callers degrade to deterministic instead of feeding wrong columns.
    """
    try:
        import lightgbm as lgb  # noqa: PLC0415

        candidates = sorted(ARTIFACT_DIR.glob("ranklet_*.txt"))
        if not candidates:
            candidates = sorted(ARTIFACT_DIR.glob("ranklet_*.model"))
        if not candidates:
            return None, None, None
        path = candidates[-1]
        version = path.stem.replace("ranklet_", "")

        feature_order: list[str] | None = None
        manifest_path = path.with_suffix(".manifest.json")
        if not manifest_path.exists():
            manifest_path = path.parent / f"{path.stem}.manifest.json"
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            feature_order = list(manifest.get("feature_order", []))
            if feature_order != FEATURE_ORDER:
                log.warning(
                    "ranklet %s manifest feature_order mismatch "
                    "(%d vs %d expected); deterministic fallback",
                    version, len(feature_order), len(FEATURE_ORDER),
                )
                return None, None, None

        booster = lgb.Booster(model_file=str(path))
        return booster, version, feature_order
    except Exception as exc:
        log.info("ranklet unavailable (%s); deterministic scoring only", exc)
        return None, None, None


def _lgbm_score(features: list[float]) -> float | None:
    booster, _version, _order = _load_lgbm()
    if booster is None:
        return None
    try:
        pred = booster.predict([features])
        value = float(pred[0])
        # LightGBM ranking scores are unbounded → squash to [0, 100]
        return max(0.0, min(100.0, value))
    except Exception:
        log.exception("ranklet prediction failed; falling back to deterministic")
        return None


def rerank(result: ScoreResult, features: list[float] | None = None) -> RankOutcome:
    """Apply the configured strategy to a completed deterministic ScoreResult.

    `features` is the M2 30-vector from `build_features`; when omitted the
    neutral component-only vector is used (legacy callers).
    """
    requested = get_settings().recommender_strategy

    if requested == "deterministic":
        return RankOutcome(final=result.final, strategy="deterministic")

    row = features if features is not None else component_vector(result)
    lgbm_value = _lgbm_score(row)
    if lgbm_value is None:
        # model not trained yet / lightgbm not installed → honest fallback
        return RankOutcome(final=result.final, strategy="deterministic")

    _booster, version, _order = _load_lgbm()
    if requested == "ltr_full":
        return RankOutcome(final=round(lgbm_value, 1), strategy="ltr_full", model_version=version)

    # ltr_blend: α·ltr + (1−α)·deterministic, contribution clamped to ±15 pts
    raw_delta = LGBM_BLEND_WEIGHT * (lgbm_value - result.final)
    delta = max(-LGBM_MAX_DELTA, min(LGBM_MAX_DELTA, raw_delta))
    blended = result.final + delta
    return RankOutcome(
        final=round(blended, 1),
        strategy="ltr_blend",
        model_version=version,
        delta_note=(
            f"Learned ranking model adjusted the deterministic score by {delta:+.1f} points."
            if abs(delta) >= 0.05
            else None
        ),
    )


def reset_cache() -> None:
    """Test hook: forget the cached booster."""
    _load_lgbm.cache_clear()
