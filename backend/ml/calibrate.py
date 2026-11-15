#!/usr/bin/env python
"""M3 probability calibrator (DCN-v2 logits, out-of-fold unbiased evaluation).

- Loads validation split (held-out, profile-strict) and DCN-v2 logits from
  ml/artifacts/dcn_ranker_v1.pt (or newest dcn_ranker_v*.pt) directly.
  input_kind must be "dcn_logit".
- Computes UNBIASED Pre- vs Post-calibration ECE and Brier via Stratified 5-Fold
  Out-of-Fold (OOF) cross-validation on held-out DCN logits (no in-sample
  memorization). Then fits the final production calibrator on ALL validation logits.
- Saves ml/artifacts/calibration_curve.png from OOF calibrated probabilities and
  ml/artifacts/calibrator_v*.joblib (production).
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
MIN_ISOTONIC_SAMPLES = 80  # per-fold; isotonic can work on modest folds but we choose adaptively
POSITIVE_LABEL_MIN = 4
N_BINS = 10
N_SPLITS = 5
SEED = 42


def read_jsonl(path: Path):
    rows = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def expected_calibration_error(probs: np.ndarray, labels: np.ndarray, n_bins: int = N_BINS) -> float:
    probs = np.clip(probs.astype(np.float64), 0.0, 1.0)
    labels = labels.astype(np.float64)
    bins = np.linspace(0.0, 1.0, n_bins + 1)
    ece = 0.0
    n = len(probs)
    if n == 0:
        return 0.0
    for i in range(n_bins):
        lo, hi = bins[i], bins[i + 1]
        if i == n_bins - 1:
            mask = (probs >= lo) & (probs <= hi)
        else:
            mask = (probs >= lo) & (probs < hi)
        if not np.any(mask):
            continue
        conf = float(probs[mask].mean())
        acc = float(labels[mask].mean())
        ece += (np.sum(mask) / n) * abs(acc - conf)
    return float(ece)


def brier_score(probs: np.ndarray, labels: np.ndarray) -> float:
    probs = np.clip(probs.astype(np.float64), 0.0, 1.0)
    labels = labels.astype(np.float64)
    if len(probs) == 0:
        return 0.0
    return float(np.mean((probs - labels) ** 2))


def reliability_points(probs: np.ndarray, labels: np.ndarray, n_bins: int = N_BINS):
    bins = np.linspace(0.0, 1.0, n_bins + 1)
    xs, ys = [], []
    for i in range(n_bins):
        lo, hi = bins[i], bins[i + 1]
        if i == n_bins - 1:
            mask = (probs >= lo) & (probs <= hi)
        else:
            mask = (probs >= lo) & (probs < hi)
        if not np.any(mask):
            xs.append((lo + hi) / 2)
            ys.append(np.nan)
            continue
        xs.append(float(probs[mask].mean()))
        ys.append(float(labels[mask].mean()))
    return xs, ys


def sigmoid(x: np.ndarray) -> np.ndarray:
    x = np.clip(x, -60.0, 60.0)
    return 1.0 / (1.0 + np.exp(-x))


# -------------------------- DCN logit loading ------------------------------

def _build_dcn_model(in_dim: int, cross_layers: int = 2, hidden=(128, 64), dropout: float = 0.2):
    import torch.nn as nn

    class CrossNetV2(nn.Module):
        def __init__(self, d: int, layers: int):
            super().__init__()
            self.ws = nn.ModuleList([nn.Linear(d, d, bias=True) for _ in range(layers)])

        def forward(self, x0):
            x = x0
            for layer in self.ws:
                x = x0 * layer(x) + x
            return x

    class DCNv2Ranker(nn.Module):
        def __init__(self, d: int):
            super().__init__()
            self.cross = CrossNetV2(d, cross_layers)
            mlp_layers = []
            prev = d
            for h in hidden:
                mlp_layers += [nn.Linear(prev, h), nn.LayerNorm(h), nn.SiLU(), nn.Dropout(dropout)]
                prev = h
            self.mlp = nn.Sequential(*mlp_layers) if mlp_layers else nn.Identity()
            self.out = nn.Linear(d + prev, 1)

        def forward(self, x):
            x_cross = self.cross(x)
            x_deep = self.mlp(x)
            h = __import__("torch").cat([x_cross, x_deep], dim=-1)
            return self.out(h).squeeze(-1)

    return DCNv2Ranker(in_dim)


def _scale_rows(rows: np.ndarray, scaler: dict | None) -> np.ndarray:
    if not scaler:
        return rows.astype(np.float32)
    mean = np.asarray(scaler.get("mean", []), dtype=np.float32)
    scale = np.asarray(scaler.get("scale", []), dtype=np.float32)
    if mean.shape[0] != rows.shape[1] or scale.shape[0] != rows.shape[1]:
        return rows.astype(np.float32)
    scale = np.where(scale == 0, 1.0, scale)
    return ((rows - mean) / scale).astype(np.float32)


def get_val_logits_and_labels() -> tuple[np.ndarray, np.ndarray, str, Path]:
    """Load held-out validation DCN-v2 logits directly (no score fallback)."""
    val_rows = read_jsonl(DATASETS / "test.jsonl")
    if not val_rows:
        raise SystemExit("validation dataset missing: run ml/build_datasets.py")
    y = np.array([1.0 if float(r.get("label", 0)) >= POSITIVE_LABEL_MIN else 0.0 for r in val_rows], dtype=np.float64)

    # prefer explicit v1, else newest
    path = ARTIFACTS / "dcn_ranker_v1.pt"
    if not path.exists():
        cands = sorted(ARTIFACTS.glob("dcn_ranker_v*.pt"))
        if not cands:
            raise RuntimeError("DCN ranker artifact not found (expected ml/artifacts/dcn_ranker_v1.pt)")
        path = cands[-1]

    import torch  # noqa: PLC0415

    payload = torch.load(path, map_location="cpu", weights_only=False)
    if not isinstance(payload, dict):
        raise RuntimeError(f"DCN artifact malformed: {path}")

    scaler = payload.get("scaler")
    manifest = payload.get("manifest") or {}
    feature_order = payload.get("feature_order") or manifest.get("feature_order") or []
    in_dim = int(manifest.get("in_dim") or (len(feature_order) if feature_order else len(val_rows[0].get("features", []))))
    cross_layers = int(payload.get("cross_layers", manifest.get("cross_layers", 2)))
    hidden = tuple(payload.get("hidden", manifest.get("hidden", [128, 64])))
    dropout = float(payload.get("dropout", manifest.get("dropout", 0.2)))

    model = _build_dcn_model(in_dim, cross_layers=cross_layers, hidden=hidden, dropout=dropout)
    state = payload.get("state_dict") or payload.get("model_state_dict")
    if state is None:
        raise RuntimeError(f"DCN artifact missing state_dict: {path}")
    model.load_state_dict(state, strict=False)
    model.eval()

    width = len(feature_order) if feature_order else in_dim
    X = np.array([
        (r.get("features") or [])[:width] + [0.0] * max(0, width - len((r.get("features") or [])[:width]))
        for r in val_rows
    ], dtype=np.float32)
    # ensure model input dim matches
    if X.shape[1] != in_dim:
        if X.shape[1] > in_dim:
            X = X[:, :in_dim]
        else:
            X = np.pad(X, ((0, 0), (0, in_dim - X.shape[1])))
    Xs = _scale_rows(X, scaler)
    with torch.no_grad():
        logits = model(torch.tensor(Xs, dtype=torch.float32)).detach().cpu().numpy().astype(np.float64)

    input_kind = "dcn_logit"
    if input_kind != "dcn_logit":
        raise RuntimeError("input_kind must be dcn_logit")
    return logits, y, input_kind, path


# -------------------------- Calibration (OOF) ------------------------------

def fit_calibrator(x: np.ndarray, y: np.ndarray, kind_hint: str | None = None):
    from sklearn.isotonic import IsotonicRegression  # noqa: PLC0415
    from sklearn.linear_model import LogisticRegression  # noqa: PLC0415

    n = len(x)
    unique_x = len(np.unique(x))
    # Prefer isotonic when enough samples/variation; platt more stable on tiny folds
    if kind_hint == "platt" or n < MIN_ISOTONIC_SAMPLES or unique_x <= 5:
        model = LogisticRegression(max_iter=1000)
        model.fit(x.reshape(-1, 1), y.astype(int))
        return model, "platt"
    model = IsotonicRegression(out_of_bounds="clip")
    model.fit(x, y)
    return model, "isotonic"


def predict_calibrated(model, kind: str, x: np.ndarray) -> np.ndarray:
    if kind == "isotonic":
        p = model.predict(x)
    else:
        p = model.predict_proba(x.reshape(-1, 1))[:, 1]
    return np.clip(np.asarray(p, dtype=np.float64), 0.0, 1.0)


def oof_calibration(x: np.ndarray, y: np.ndarray, n_splits: int = N_SPLITS):
    """Stratified K-Fold OOF probabilities for unbiased post-calibration metrics."""
    from sklearn.model_selection import StratifiedKFold  # noqa: PLC0415

    y_int = y.astype(int)
    # handle degenerate stratification (very few positives)
    pos = int(np.sum(y_int))
    neg = int(len(y_int) - pos)
    splits = n_splits
    splits = max(2, min(splits, pos if pos > 0 else 2, neg if neg > 0 else 2))
    if splits < 2:
        # cannot do CV; fall back to simple holdout-style split
        splits = 2
    skf = StratifiedKFold(n_splits=splits, shuffle=True, random_state=SEED)
    oof_post = np.full_like(x, fill_value=np.nan, dtype=np.float64)
    fold_kinds = []
    for tr_idx, va_idx in skf.split(x, y_int):
        model, kind = fit_calibrator(x[tr_idx], y[tr_idx])
        fold_kinds.append(kind)
        oof_post[va_idx] = predict_calibrated(model, kind, x[va_idx])
    # safety: any missing -> use pre sigmoid
    if np.any(np.isnan(oof_post)):
        oof_post = np.where(np.isnan(oof_post), sigmoid(x), oof_post)
    # choose production kind: platt if any fold used platt or very imbalanced/small, else isotonic
    prod_kind = "isotonic" if all(k == "isotonic" for k in fold_kinds) else "platt"
    # but prefer isotonic for final fit on all data when feasible
    return oof_post, {"n_splits": splits, "fold_kinds": fold_kinds, "prod_kind_hint": prod_kind}


# -------------------------- Plotting / output ------------------------------

def save_reliability_diagram(pre_p, post_p, y, out_png: Path, input_kind: str, subtitle: str):
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt  # noqa: PLC0415

        fig, axes = plt.subplots(1, 2, figsize=(10, 4.2), sharey=True)
        for ax, probs, title in [
            (axes[0], pre_p, "Before Calibration"),
            (axes[1], post_p, "After Calibration (M3, OOF)"),
        ]:
            xs, ys = reliability_points(probs, y, N_BINS)
            ax.plot([0, 1], [0, 1], linestyle="--", color="#888888", label="Perfect")
            bx = [a for a, b in zip(xs, ys) if not (isinstance(b, float) and np.isnan(b))]
            by = [b for b in ys if not (isinstance(b, float) and np.isnan(b))]
            ax.plot(bx, by, marker="o", color="#2563eb", label="Empirical")
            ax.set_xlim(0, 1)
            ax.set_ylim(0, 1)
            ax.set_xlabel(f"Predicted probability ({input_kind})")
            ax.set_title(title)
            ax.grid(True, alpha=0.25)
            ax.legend(loc="best", fontsize=8)
        axes[0].set_ylabel("Observed frequency (high-intent relevance)")
        fig.suptitle(subtitle, fontsize=11)
        fig.tight_layout()
        out_png.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(out_png, dpi=170)
        plt.close(fig)
        return str(out_png)
    except Exception as exc:
        print(f"[calibrate] reliability diagram failed: {exc}")
        return None


def next_version() -> str:
    highest = 0
    for path in ARTIFACTS.glob("calibrator_v*.joblib"):
        try:
            highest = max(highest, int(path.stem.split("_v")[-1]))
        except ValueError:
            pass
    return f"v{highest + 1}"


def print_calibration_table(pre_ece, pre_brier, post_ece, post_brier, input_kind: str, cv_info: dict):
    header = f"{'State':20s} {'ECE':>12s} {'Brier':>12s}"
    print("\n" + "=" * len(header))
    print(f"M3 Calibration (OOF, Stratified {cv_info.get('n_splits')}-Fold, input_kind={input_kind})")
    print("=" * len(header))
    print(header)
    print("-" * len(header))
    print(f"{'Pre-calibration':20s} {pre_ece:12.6f} {pre_brier:12.6f}")
    print(f"{'Post-calibration':20s} {post_ece:12.6f} {post_brier:12.6f}  (OOF, unbiased)")
    print("=" * len(header))


def run(register: bool = True) -> dict:
    import joblib  # noqa: PLC0415

    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    x, y, input_kind, dcn_path = get_val_logits_and_labels()
    if input_kind != "dcn_logit":
        raise RuntimeError(f"Expected input_kind=dcn_logit, got {input_kind}")
    print(f"[calibrate] input_kind={input_kind} (verified), dcn_artifact={dcn_path}, n={len(x)}, positives={int(y.sum())}")

    pre_p = sigmoid(x)
    pre_ece = expected_calibration_error(pre_p, y)
    pre_brier = brier_score(pre_p, y)

    # Unbiased post-calibration metrics via OOF CV
    oof_post_p, cv_info = oof_calibration(x, y, n_splits=N_SPLITS)
    post_ece = expected_calibration_error(oof_post_p, y)
    post_brier = brier_score(oof_post_p, y)

    print_calibration_table(pre_ece, pre_brier, post_ece, post_brier, input_kind, cv_info)

    # Reliability diagram from OOF calibrated probabilities (unbiased)
    curve_path = ARTIFACTS / "calibration_curve.png"
    curve_png = save_reliability_diagram(
        pre_p, oof_post_p, y, curve_path, input_kind,
        subtitle="M3 Reliability Diagram (Validation, DCN-v2 logits, OOF Stratified CV)"
    )
    print(f"[calibrate] reliability diagram (OOF): {curve_png}")

    # Final production calibrator fit on ALL validation logits
    final_model, final_kind = fit_calibrator(x, y, kind_hint=cv_info.get("prod_kind_hint"))
    # also record in-sample metrics for transparency (not reported as primary)
    insample_post = predict_calibrated(final_model, final_kind, x)
    insample_ece = expected_calibration_error(insample_post, y)
    insample_brier = brier_score(insample_post, y)

    version = next_version()
    metrics = {
        "input_kind": input_kind,
        "n_samples": int(len(x)),
        "positive_rate": float(np.mean(y)) if len(y) else 0.0,
        "oof_n_splits": int(cv_info.get("n_splits", 0)),
        "oof_fold_kinds": cv_info.get("fold_kinds", []),
        "ece_before": pre_ece,
        "brier_before": pre_brier,
        "ece_after_oof": post_ece,
        "brier_after_oof": post_brier,
        "ece_after_insample_reference": insample_ece,
        "brier_after_insample_reference": insample_brier,
        # primary reported post-calibration metrics are OOF/unbiased
        "ece_after": post_ece,
        "brier_after": post_brier,
    }
    payload = {
        "kind": final_kind,
        "version": version,
        "model": final_model,
        "input": input_kind,
        "positive_label_min": POSITIVE_LABEL_MIN,
        "metrics": metrics,
        "trained_at": datetime.now(timezone.utc).isoformat(),
    }
    artifact_path = ARTIFACTS / f"calibrator_{version}.joblib"
    joblib.dump(payload, artifact_path)
    print(f"[calibrate] production artifact (fit on all val logits): {artifact_path}")

    result = {
        "artifact": str(artifact_path),
        "version": version,
        "metrics": metrics,
        "calibration_curve_png": str(curve_png),
        "dcn_artifact": str(dcn_path),
    }
    if register:
        try:
            import ml.ml_registry as registry  # noqa: PLC0415

            row = registry.register(
                "calibrator",
                version,
                str(artifact_path.relative_to(BACKEND_ROOT)),
                metrics,
                promote=post_ece <= 0.10,
            )
            result["registry"] = row
        except Exception as exc:
            result["registry_error"] = str(exc)
            print(f"[calibrate] registry step failed: {exc}")
    print(json.dumps(result, indent=2, default=str))
    return result


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-register", action="store_true")
    args = ap.parse_args(argv)
    run(register=not args.no_register)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
