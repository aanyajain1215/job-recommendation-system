"""Runtime configuration store — precedence for scoring weights (plan §7).

Precedence: defaults (``scoring.DEFAULT_WEIGHTS``) → ``system_config`` row
(admin panel, ``PUT /admin/config``) → env overrides.  The LLM never reads
or writes this store; validation is deterministic and Σw = 1 is enforced on
save (plan §7 "Weights validated Σ=1 on save").
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.ops import SystemConfig
from app.services.scoring import DEFAULT_WEIGHTS

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
    """Effective global weight vector: defaults overlaid with the admin row."""
    row = db.get(SystemConfig, SCORING_WEIGHTS_KEY)
    if row is None or not isinstance(row.value, dict):
        return dict(DEFAULT_WEIGHTS)
    try:
        return validate_weights(row.value)
    except ValueError:
        # Never let a corrupt admin row break the feed — fall back to code defaults.
        return dict(DEFAULT_WEIGHTS)


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
