"""Ranklet strategy dispatch (plan §6/§17).

Three strategies, selected by settings.recommender_strategy:

- deterministic — pure component weights (default; always available)
- ltr_blend     — 70% deterministic + 30% LightGBM LambdaRank (M2)
- ltr_full      — LightGBM score only

The M2 model is optional: if the artifact or lightgbm is missing, every
strategy silently degrades to `deterministic` and reports the effective
strategy so the API/UI never lies about what produced the ranking.  The LLM
never participates here — all numbers come from scoring.py or the trained
artifact.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.services.scoring import ScoreResult

log = logging.getLogger(__name__)

ARTIFACT_DIR = Path(__file__).resolve().parents[2] / "ml" / "artifacts"
# plan §17: ltr_blend uses α=0.35, contribution clamped to ±15 points
LGBM_BLEND_WEIGHT = 0.35
LGBM_MAX_DELTA = 15.0
FEATURE_ORDER = [
    "semantic",
    "skill",
    "experience",
    "education",
    "project",
    "location",
    "salary",
    "interest",
]


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


@lru_cache
def _load_lgbm():
    """Load the active ranklet artifact. Returns (booster, version) or (None, None)."""
    try:
        import lightgbm as lgb  # noqa: PLC0415

        candidates = sorted(ARTIFACT_DIR.glob("ranklet_*.txt"))
        if not candidates:
            candidates = sorted(ARTIFACT_DIR.glob("ranklet_*.model"))
        if not candidates:
            return None, None
        path = candidates[-1]
        booster = lgb.Booster(model_file=str(path))
        version = path.stem.replace("ranklet_", "")
        return booster, version
    except Exception as exc:
        log.info("ranklet unavailable (%s); deterministic scoring only", exc)
        return None, None


def _lgbm_score(components: dict[str, float]) -> float | None:
    booster, _version = _load_lgbm()
    if booster is None:
        return None
    try:
        row = [[float(components.get(name, 50.0)) for name in FEATURE_ORDER]]
        pred = booster.predict(row)
        value = float(pred[0])
        # LightGBM ranking scores are unbounded → squash to [0, 100]
        return max(0.0, min(100.0, value))
    except Exception:
        log.exception("ranklet prediction failed; falling back to deterministic")
        return None


def rerank(result: ScoreResult) -> RankOutcome:
    """Apply the configured strategy to a completed deterministic ScoreResult."""
    requested = get_settings().recommender_strategy

    if requested == "deterministic":
        return RankOutcome(final=result.final, strategy="deterministic")

    lgbm_value = _lgbm_score(result.components)
    if lgbm_value is None:
        # model not trained yet / lightgbm not installed → honest fallback
        return RankOutcome(final=result.final, strategy="deterministic")

    booster, version = _load_lgbm()
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
