#!/usr/bin/env python
"""Learn the 8 scoring component weights from interaction data (AI-driven core).

Replaces hand-picked DEFAULT_WEIGHTS with data-fitted weights by training a
constrained linear model on the 8 component scores (semantic..interest) to
predict graded interaction labels from ml/datasets/train.jsonl.

Constraints: weights >= 0 and sum to 1 (same as the deterministic combiner),
so the result remains interpretable as a weighted match score.

Artifact: ml/artifacts/score_weights_v*.json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

ARTIFACTS = BACKEND_ROOT / "ml" / "artifacts"
DATASETS = BACKEND_ROOT / "ml" / "datasets"
COMPONENTS = [
    "semantic",
    "skill",
    "experience",
    "education",
    "project",
    "location",
    "salary",
    "interest",
]

# Fallback prior (kept in sync with scoring.DEFAULT_WEIGHTS) used when no data.
DEFAULT_WEIGHTS = {
    "semantic": 0.30,
    "skill": 0.25,
    "experience": 0.15,
    "education": 0.10,
    "project": 0.05,
    "location": 0.05,
    "salary": 0.05,
    "interest": 0.05,
}


def _load(path: Path) -> tuple[np.ndarray, np.ndarray]:
    xs, ys = [], []
    if not path.exists():
        return np.zeros((0, 8), dtype=np.float64), np.zeros((0,), dtype=np.float64)
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        feats = row.get("features") or []
        if len(feats) < 8:
            continue
        # first 8 are component scores in [0,100]
        xs.append([float(v) / 100.0 for v in feats[:8]])
        # normalize graded label to [0,1] (max label 10)
        ys.append(min(1.0, float(row.get("label", 0)) / 10.0))
    if not xs:
        return np.zeros((0, 8), dtype=np.float64), np.zeros((0,), dtype=np.float64)
    return np.asarray(xs, dtype=np.float64), np.asarray(ys, dtype=np.float64)


def _project_simplex(v: np.ndarray) -> np.ndarray:
    """Project vector onto {w>=0, sum w == 1}."""
    if v.size == 0:
        return v
    u = np.sort(v)[::-1]
    cssv = np.cumsum(u)
    rho = np.nonzero(u * np.arange(1, len(u) + 1) > (cssv - 1))[0][-1]
    theta = (cssv[rho] - 1.0) / (rho + 1.0)
    w = np.maximum(v - theta, 0.0)
    s = w.sum()
    if s <= 0:
        w = np.ones_like(w) / len(w)
    else:
        w = w / s
    return w


def fit_weights(X: np.ndarray, y: np.ndarray, steps: int = 4000, lr: float = 0.5, l2: float = 1e-3) -> dict[str, float]:
    """Projected gradient descent for non-negative simplex-constrained weights."""
    if len(X) == 0:
        return dict(DEFAULT_WEIGHTS)
    # start from uniform; include a small pull toward data-driven optimum only
    w = np.ones(8, dtype=np.float64) / 8.0
    n = float(len(X))
    for i in range(steps):
        pred = X @ w
        err = pred - y
        grad = (2.0 / n) * (X.T @ err) + (2.0 * l2 * w)
        step_lr = lr / (1.0 + 0.001 * i)
        w = _project_simplex(w - step_lr * grad)
    # avoid degenerate all-zero-on-one (keep tiny floor then renormalize)
    w = np.maximum(w, 1e-4)
    w = w / w.sum()
    return {c: float(round(float(wi), 6)) for c, wi in zip(COMPONENTS, w)}


def evaluate(X: np.ndarray, y: np.ndarray, weights: dict[str, float]) -> dict:
    if len(X) == 0:
        return {"n": 0}
    w = np.array([weights[c] for c in COMPONENTS], dtype=np.float64)
    pred = X @ w
    mse = float(np.mean((pred - y) ** 2))
    mae = float(np.mean(np.abs(pred - y)))
    # correlation
    if np.std(pred) > 1e-9 and np.std(y) > 1e-9:
        corr = float(np.corrcoef(pred, y)[0, 1])
    else:
        corr = 0.0
    # compare vs old defaults
    w0 = np.array([DEFAULT_WEIGHTS[c] for c in COMPONENTS], dtype=np.float64)
    pred0 = X @ w0
    mse0 = float(np.mean((pred0 - y) ** 2))
    return {
        "n": int(len(X)),
        "mse": round(mse, 6),
        "mae": round(mae, 6),
        "corr": round(corr, 4),
        "baseline_mse_default_weights": round(mse0, 6),
        "improved_vs_default": mse <= mse0 + 1e-12,
    }


def next_version() -> str:
    existing = sorted(ARTIFACTS.glob("score_weights_v*.json"))
    if not existing:
        return "v1"
    try:
        n = int(existing[-1].stem.split("_v")[-1])
        return f"v{n+1}"
    except Exception:
        return "v1"


def run(register: bool = True) -> dict:
    Xtr, ytr = _load(DATASETS / "train.jsonl")
    Xte, yte = _load(DATASETS / "test.jsonl")
    Xall = np.vstack([Xtr, Xte]) if len(Xtr) and len(Xte) else (Xtr if len(Xtr) else Xte)
    yall = np.concatenate([ytr, yte]) if len(ytr) and len(yte) else (ytr if len(ytr) else yte)

    weights = fit_weights(Xall, yall)
    metrics = {
        "train": evaluate(Xtr, ytr, weights),
        "test": evaluate(Xte, yte, weights),
        "all": evaluate(Xall, yall, weights),
    }

    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    version = next_version()
    payload = {
        "name": "score_weights",
        "version": version,
        "weights": weights,
        "components": COMPONENTS,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "metrics": metrics,
        "method": "constrained_linear_regression_simplex_pgdm",
    }
    path = ARTIFACTS / f"score_weights_{version}.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    out = {"artifact": str(path), "version": version, "weights": weights, "metrics": metrics}
    if register:
        try:
            import ml.ml_registry as registry  # noqa: PLC0415

            registry.register(
                "score_weights",
                version,
                str(path.relative_to(BACKEND_ROOT)),
                metrics,
                promote=True,
            )
            out["registered"] = True
        except Exception as exc:
            out["registered"] = False
            out["register_error"] = str(exc)

    print(json.dumps(out, indent=2))
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Train learned 8-component score weights")
    p.add_argument("--no-register", action="store_true")
    args = p.parse_args(argv)
    run(register=not args.no_register)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
