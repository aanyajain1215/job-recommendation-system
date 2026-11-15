"""Runtime configuration store — precedence for scoring weights (plan §7).

Precedence: defaults (``scoring.DEFAULT_WEIGHTS``) → learned AI weights artifact
(data-fitted, when present) → ``system_config`` row (admin panel override).
Validation is deterministic and Σw = 1 is enforced on save.
"""

from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.ops import SystemConfig
from app.services.scoring import DEFAULT_WEIGHTS

ARTIFACT_DIR = Path(__file__).resolve().parents[2] / "ml" / "artifacts"


def _learned_weights_from_artifact() -> dict[str, float] | None:
    """Load latest learned score weights (AI-fitted) if available."""
    try:
        if not ARTIFACT_DIR.exists():
            return None
        cands = sorted(ARTIFACT_DIR.glob("score_weights_v*.json"))
        if not cands:
            return None
        payload = json.loads(cands[-1].read_text(encoding="utf-8"))
        weights = payload.get("weights") or {}
        return validate_weights(weights)
    except Exception:
        return None

SCORING_WEIGHTS_KEY = "scoring_weights"
WEIGHT_TOLERANCE = 1e-6

# UI labels for the admin/settings panels (kept local to avoid import cycles)
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


def validate_weights(raw: Any) -> dict[str, float]:
    """Validate an admin-supplied weight vector; raise ``ValueError`` with a
    human-readable reason when it cannot be trusted by the scoring engine."""
    if not isinstance(raw, dict):
        raise ValueError("weights must be an object mapping component → number")

    missing = [k for k in DEFAULT_WEIGHTS if k not in raw]
    if missing:
        raise ValueError(f"missing components: {', '.join(missing)}")
    extra = [k for k in raw if k not in DEFAULT_WEIGHTS]
    if extra:
        raise ValueError(f"unknown components: {', '.join(extra)}")

    out: dict[str, float] = {}
    for key in DEFAULT_WEIGHTS:
        try:
            value = float(raw[key])  # type: ignore[arg-type]
        except (TypeError, ValueError):
            raise ValueError(f"component '{key}' must be a number") from None
        if value < 0:
            raise ValueError(f"component '{key}' must be >= 0")
        out[key] = value

    total = sum(out.values())
    if abs(total - 1.0) > 1e-4:
        raise ValueError(f"weights must sum to 1.0 (got {total:.6f})")
    # renormalise tiny float drift so stored Σ is exactly within tolerance
    if abs(total - 1.0) > WEIGHT_TOLERANCE:
        out = {k: v / total for k, v in out.items()}
    return out


def get_scoring_weights(db: Session) -> dict[str, float]:
    """Effective global weight vector.

    AI-first: prefer data-learned weights artifact when present, then apply the
    admin `system_config` override if set. Falls back to code defaults if
    artifacts/config are missing or invalid.
    """
    base = _learned_weights_from_artifact() or dict(DEFAULT_WEIGHTS)
    row = db.get(SystemConfig, SCORING_WEIGHTS_KEY)
    if row is None or not isinstance(row.value, dict):
        return base
    try:
        return validate_weights(row.value)
    except ValueError:
        # Never let a corrupt admin row break the feed — fall back to learned/default base.
        return base


def has_custom_weights(db: Session) -> bool:
    row = db.get(SystemConfig, SCORING_WEIGHTS_KEY)
    return row is not None and isinstance(row.value, dict)


def set_scoring_weights(
    db: Session,
    weights: Any,
    updated_by_user_id: UUID | None = None,
) -> dict[str, float]:
    """Persist the admin weight vector (Σw=1 validated). Returns saved weights."""
    clean = validate_weights(weights)
    row = db.get(SystemConfig, SCORING_WEIGHTS_KEY)
    if row is None:
        row = SystemConfig(
            key=SCORING_WEIGHTS_KEY,
            value=clean,
            description="Global scoring weights (plan §7 config precedence)",
            updated_by_user_id=updated_by_user_id,
        )
        db.add(row)
    else:
        row.value = clean
        row.updated_by_user_id = updated_by_user_id
        row.updated_at = datetime.now(timezone.utc)
    return clean


def component_catalog() -> list[dict[str, Any]]:
    """Read-only component list for the admin config panel."""
    return [
        {"component": k, "label": COMPONENT_LABELS.get(k, k.capitalize()),
         "default": DEFAULT_WEIGHTS[k]}
        for k in DEFAULT_WEIGHTS
    ]
