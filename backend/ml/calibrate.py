#!/usr/bin/env python
"""M3 score calibrator (plan §6 M3 / §17 / §21).

Isotonic regression (Platt sigmoid fallback below 500 labels) mapping the
displayed deterministic score → P(positive outcome), where positive means a
graded label ≥ `settings.calibrator_positive_min` (default 4 = save or
better).  Fitted on ALL dataset rows (train + test) because calibration is a
post-hoc display concern, not a ranking claim — §21 gates it on ECE.

Artifact: ml/artifacts/calibrator_v{N}.joblib
    {"kind": "isotonic"|"platt", "version", "model", "metrics", "trained_at"}
Serving: app/services/calibration.py (falls back to the raw Phase-1 mapping
when absent/disabled).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

ARTIFACTS = BACKEND_ROOT / "ml" / "artifacts"
DATASETS = BACKEND_ROOT / "ml" / "datasets"
MIN_ISOTONIC_SAMPLES = 500


def load_rows(paths: list[Path]) -> tuple[list[float], list[int]]:
    scores: list[float] = []
    labels: list[int] = []
    for path in paths:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            scores.append(float(row["score"]))
            labels.append(int(row["label"]))
    return scores, labels


def next_version() -> str:
    highest = 0
    for path in ARTIFACTS.glob("calibrator_v*.joblib"):
        try:
            highest = max(highest, int(path.stem.split("_v")[-1]))
        except ValueError:
            continue
    return f"v{highest + 1}"


def run(register: bool = True) -> dict:
    try:
        import joblib  # noqa: PLC0415
        from sklearn.isotonic import IsotonicRegression  # noqa: PLC0415
        from sklearn.linear_model import LogisticRegression  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(f"scikit-learn required for M3: {exc}")

    from app.core.config import get_settings  # noqa: PLC0415
    from ml.metrics import brier_score, expected_calibration_error  # noqa: PLC0415

    scores, labels = load_rows([DATASETS / "train.jsonl", DATASETS / "test.jsonl"])
    if not scores:
        raise SystemExit("[calibrator] datasets missing — run ml/build_datasets.py first")

    threshold = get_settings().calibrator_positive_min
    y = [1 if label >= threshold else 0 for label in labels]
    positive_rate = sum(y) / len(y)

    if len(scores) >= MIN_ISOTONIC_SAMPLES:
        kind = "isotonic"
        model = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
        model.fit(scores, y)
        probs = [float(p) for p in model.predict(scores)]
    else:
        kind = "platt"
        model = LogisticRegression(solver="lbfgs")
        model.fit([[s] for s in scores], y)
        probs = [float(p) for p in model.predict_proba([[s] for s in scores])[:, 1]]

    metrics = {
        "kind": kind,
        "n": len(scores),
        "positive_rate": round(positive_rate, 4),
        "brier": round(brier_score(probs, y), 4),
        "ece": round(expected_calibration_error(probs, y), 4),
        "positive_threshold_label": threshold,
    }

    version = next_version()
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    artifact_path = ARTIFACTS / f"calibrator_{version}.joblib"
    joblib.dump(
        {
            "kind": kind,
            "version": version,
            "model": model,
            "metrics": metrics,
            "trained_at": datetime.now(timezone.utc).isoformat(),
        },
        artifact_path,
    )

    result = {"artifact": str(artifact_path), "version": version, "metrics": metrics}

    if register:
        import ml.ml_registry as registry  # noqa: PLC0415

        row = registry.register(
            "isotonic-calibrator",
            version,
            str(artifact_path.relative_to(BACKEND_ROOT)),
            metrics,
            promote=True,
        )
        result["registry"] = row

    print(json.dumps(result, indent=2))
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fit M3 score calibrator")
    parser.add_argument("--no-register", action="store_true")
    args = parser.parse_args(argv)
    run(register=not args.no_register)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
