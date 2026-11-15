"""M3 readiness/probability calibration.

Isotonic regression (Platt fallback) mapping model output to P(positive outcome).
Trained by ml/calibrate.py. Supports calibration on DCN-v2 logits (preferred) or
fallback score inputs. No LLM involved.
"""

from __future__ import annotations

import logging
import math
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np

from app.core.config import get_settings

log = logging.getLogger(__name__)

ARTIFACT_DIR = Path(__file__).resolve().parents[2] / "ml" / "artifacts"


def _sigmoid(x: float) -> float:
    x = max(-60.0, min(60.0, float(x)))
    return 1.0 / (1.0 + math.exp(-x))


@lru_cache
def load_calibrator() -> dict[str, Any]:
    """Newest calibrator payload. AI-strict: required."""
    candidates = sorted(ARTIFACT_DIR.glob("calibrator_v*.joblib"))
    if not candidates:
        raise RuntimeError("Calibrator model artifact required but none found (expected calibrator_v*.joblib)")
    import joblib  # noqa: PLC0415

    payload = joblib.load(candidates[-1])
    if not isinstance(payload, dict) or "model" not in payload:
        raise RuntimeError("Calibrator artifact malformed: expected payload with 'model'")
    return payload


def _predict_with_model(model: Any, kind: str, x: float) -> float:
    if kind == "isotonic":
        prob = float(model.predict([x])[0])
    else:
        # Platt / logistic on 1d feature
        prob = float(model.predict_proba([[x]])[0][1])
    return float(max(0.0, min(1.0, prob)))


def predict_positive(score: float, *, logit: float | None = None) -> float:
    """P(positive outcome) calibrated, clamped to [0,1].

    - If calibrator was fit on DCN logits and `logit` is provided, calibrate on logit.
    - If calibrator expects DCN logits but only `score` (0-100 prob proxy) is given,
      convert prob proxy back to logit as best-effort.
    - If calibrator expects score, use score.
    """
    if not get_settings().readiness_calibrator_enabled:
        raise RuntimeError("Readiness calibrator is disabled but AI-strict calibration is required")

    payload = load_calibrator()
    model = payload["model"]
    kind = str(payload.get("kind", "isotonic"))
    input_kind = str(payload.get("input", "score"))

    if input_kind == "dcn_logit":
        if logit is not None:
            x = float(logit)
        else:
            # score is 0-100 => prob proxy; invert to logit
            p = float(max(1e-6, min(1 - 1e-6, float(score) / 100.0)))
            x = math.log(p / (1.0 - p))
    else:
        x = float(score)

    try:
        prob = _predict_with_model(model, kind, x)
    except Exception as exc:
        raise RuntimeError(f"Calibrator inference failed (AI-strict, no fallback): {exc}") from exc
    return prob


def reset_cache() -> None:
    load_calibrator.cache_clear()
