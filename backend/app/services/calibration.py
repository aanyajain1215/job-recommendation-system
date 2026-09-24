"""M3 readiness calibration (plan §6/§17).

Isotonic regression (Platt fallback below 500 labels) mapping a displayed
score to P(positive outcome).  Trained by ``ml/calibrate.py``, versioned in
``model_registry``; serving loads the newest ``calibrator_v*.joblib`` from
``ml/artifacts``.

Degradation contract: no artifact, disabled via
``readiness_calibrator_enabled=false``, or a load/predict failure all return
``None`` so callers fall back to the Phase-1 raw mapping — the LLM is never
involved and the output shape never changes.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.core.config import get_settings

log = logging.getLogger(__name__)

ARTIFACT_DIR = Path(__file__).resolve().parents[2] / "ml" / "artifacts"


@lru_cache
def load_calibrator() -> dict[str, Any] | None:
    """Newest calibrator payload ({"kind","version","model","metrics"}) or None."""
    try:
        candidates = sorted(ARTIFACT_DIR.glob("calibrator_v*.joblib"))
        if not candidates:
            return None
        import joblib  # noqa: PLC0415

        payload = joblib.load(candidates[-1])
        if not isinstance(payload, dict) or "model" not in payload:
            log.warning("calibrator artifact malformed; ignoring")
            return None
        return payload
    except Exception as exc:  # pragma: no cover - defensive degradation
        log.info("calibrator unavailable (%s); using raw readiness mapping", exc)
        return None


def predict_positive(score: float) -> float | None:
    """P(positive outcome) for a displayed score, clamped to [0, 1]; None = fall back."""
    if not get_settings().readiness_calibrator_enabled:
        return None
    payload = load_calibrator()
    if payload is None:
        return None
    try:
        model = payload["model"]
        kind = payload.get("kind", "isotonic")
        if kind == "platt":
            value = float(model.predict([[float(score)]])[0])
        else:  # isotonic expects a 1-D sequence
            value = float(model.predict([float(score)])[0])
        return max(0.0, min(1.0, value))
    except Exception:
        log.exception("calibrator prediction failed; using raw readiness mapping")
        return None


def reset_cache() -> None:
    """Test hook: forget the cached artifact."""
    load_calibrator.cache_clear()
