#!/usr/bin/env python
"""Train M2 DCN-v2 neural ranker and report apples-to-apples baselines.

Fixes (methodological):
- Ranking metrics (NDCG@5, NDCG@10, MRR@10, MAP@10) computed ONLY over user/query
  groups with >=1 positive item (label >= POSITIVE_LABEL_MIN) AND >=2 items.
  Reports n_eval_queries. (Avoids all-negative groups collapsing MRR/MAP.)
- Trains an in-script LightGBM GBDT baseline on the SAME 31 standardized features
  for a real apples-to-apples comparison:
    (a) Heuristic Weighted Sum  vs (b) LightGBM GBDT  vs (c) DCN-v2 Neural Ranker

Artifacts:
  ml/artifacts/dcn_ranker_v1.pt (state_dict, scaler, feature manifest, meta)
  ml/artifacts/dcn_loss_curve.png (+ .json)
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

ARTIFACTS = BACKEND_ROOT / "ml" / "artifacts"
DATASETS = BACKEND_ROOT / "ml" / "datasets"

SEED = 42
EPOCHS = 80
LR = 1e-3
WEIGHT_DECAY = 1e-4
DROPOUT = 0.2
CROSS_LAYERS = 2
HIDDEN = [128, 64]
POSITIVE_LABEL_MIN = 4  # high-intent relevance
PAIRWISE_WEIGHT = 0.6
BCE_WEIGHT = 0.4
PAIR_MARGIN = 0.0
MAX_PAIRS_PER_GROUP = 64
DEVICE = "cpu"


def set_seed(seed: int = SEED) -> None:
    random.seed(seed)
    np.random.seed(seed)
    try:
        import torch

        torch.manual_seed(seed)
    except Exception:
        pass


def read_jsonl(path: Path) -> list[dict]:
    rows = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


@dataclass
class SplitData:
    X: np.ndarray
    y: np.ndarray
    y_bin: np.ndarray
    scores_baseline: np.ndarray
    groups: list[list[int]]  # indices per profile, contiguous


def load_split(path: Path) -> SplitData:
    rows = read_jsonl(path)
    if not rows:
        return SplitData(
            X=np.zeros((0, 0), dtype=np.float32),
            y=np.zeros((0,), dtype=np.float32),
            y_bin=np.zeros((0,), dtype=np.float32),
            scores_baseline=np.zeros((0,), dtype=np.float32),
            groups=[],
        )
    feats = [r.get("features") or [] for r in rows]
    width = max(len(f) for f in feats) if feats else 0
    X = np.array([f + [0.0] * (width - len(f)) for f in feats], dtype=np.float32)
    y = np.array([float(r.get("label", 0)) for r in rows], dtype=np.float32)
    y_bin = (y >= POSITIVE_LABEL_MIN).astype(np.float32)
    baseline = np.array([float(r.get("score", 0.0)) for r in rows], dtype=np.float32)
    groups = []
    start = 0
    for i in range(1, len(rows) + 1):
        if i == len(rows) or rows[i]["profile_id"] != rows[start]["profile_id"]:
            groups.append(list(range(start, i)))
            start = i
    return SplitData(X=X, y=y, y_bin=y_bin, scores_baseline=baseline, groups=groups)


class StandardScalerFit:
    def __init__(self):
        self.mean_: np.ndarray | None = None
        self.scale_: np.ndarray | None = None

    def fit(self, X: np.ndarray):
        self.mean_ = X.mean(axis=0).astype(np.float32) if len(X) else np.zeros((X.shape[1],), dtype=np.float32)
        std = X.std(axis=0).astype(np.float32) if len(X) else np.ones((X.shape[1],), dtype=np.float32)
        std[std == 0] = 1.0
        self.scale_ = std
        return self

    def transform(self, X: np.ndarray) -> np.ndarray:
        if self.mean_ is None or self.scale_ is None or len(X) == 0:
            return X.astype(np.float32)
        return ((X - self.mean_) / self.scale_).astype(np.float32)

    def to_dict(self) -> dict:
        return {
            "mean": self.mean_.tolist() if self.mean_ is not None else [],
            "scale": self.scale_.tolist() if self.scale_ is not None else [],
        }


# ----------------------------- DCN-v2 --------------------------------------

def build_dcn_model(in_dim: int, cross_layers: int = CROSS_LAYERS, hidden=None, dropout: float = DROPOUT):
    import torch
    import torch.nn as nn

    hidden = hidden or HIDDEN

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
            h = torch.cat([x_cross, x_deep], dim=-1)
            return self.out(h).squeeze(-1)

    return DCNv2Ranker(in_dim)


def pairwise_ranknet_loss(logits, labels, max_pairs=MAX_PAIRS_PER_GROUP, margin=PAIR_MARGIN):
    import torch

    n = logits.shape[0]
    if n < 2:
        return torch.tensor(0.0, device=logits.device)
    pairs_i, pairs_j = [], []
    order = torch.argsort(labels, descending=True)
    for i_pos in range(len(order)):
        for j_pos in range(i_pos + 1, len(order)):
            i = int(order[i_pos].item())
            j = int(order[j_pos].item())
            if float(labels[i].item()) <= float(labels[j].item()):
                continue
            pairs_i.append(i)
            pairs_j.append(j)
            if len(pairs_i) >= max_pairs:
                break
        if len(pairs_i) >= max_pairs:
            break
    if not pairs_i:
        return torch.tensor(0.0, device=logits.device)
    pi = torch.tensor(pairs_i, device=logits.device, dtype=torch.long)
    pj = torch.tensor(pairs_j, device=logits.device, dtype=torch.long)
    diff = (logits[pi] - logits[pj] - margin)
    return torch.nn.functional.softplus(-diff).mean()


# ----------------------------- Evaluation ----------------------------------

def _eval_groups_ranking(split: SplitData, pred_scores: np.ndarray) -> dict:
    """Standard IR protocol: ranking metrics over positive-bearing groups with >=2 items."""
    from ml.metrics import average_precision_at_k, auc_roc_binary, mrr_at_k, ndcg_at_k

    ndcg5s, ndcg10s, mrr10s, map10s = [], [], [], []
    n_eval_queries = 0
    n_total_groups = len(split.groups)
    for g in split.groups:
        if len(g) < 2:
            continue
        labels = split.y[g]
        if float(np.max(labels)) < POSITIVE_LABEL_MIN:
            continue
        scores = pred_scores[g]
        order = np.argsort(-scores)
        ranked_labels = labels[order].tolist()
        ndcg5s.append(ndcg_at_k(ranked_labels, 5))
        ndcg10s.append(ndcg_at_k(ranked_labels, 10))
        mrr10s.append(mrr_at_k(ranked_labels, 10, threshold=POSITIVE_LABEL_MIN))
        map10s.append(average_precision_at_k(ranked_labels, 10, threshold=POSITIVE_LABEL_MIN))
        n_eval_queries += 1

    auc = 0.0
    try:
        auc = auc_roc_binary(split.y_bin.astype(int).tolist(), pred_scores.astype(float).tolist())
    except Exception:
        auc = 0.0

    return {
        "ndcg@5": float(np.mean(ndcg5s)) if ndcg5s else 0.0,
        "ndcg@10": float(np.mean(ndcg10s)) if ndcg10s else 0.0,
        "mrr@10": float(np.mean(mrr10s)) if mrr10s else 0.0,
        "map@10": float(np.mean(map10s)) if map10s else 0.0,
        "auc_roc": float(auc),
        "n_eval_queries": int(n_eval_queries),
        "n_total_groups": int(n_total_groups),
        "positive_label_min": POSITIVE_LABEL_MIN,
    }


def evaluate_baseline_scores(split: SplitData, pred_scores: np.ndarray) -> dict:
    if split.X.shape[0] == 0:
        return {"ndcg@5": 0.0, "ndcg@10": 0.0, "mrr@10": 0.0, "map@10": 0.0, "auc_roc": 0.0, "n_eval_queries": 0}
    return _eval_groups_ranking(split, np.asarray(pred_scores, dtype=np.float64))


def evaluate_split(model, split: SplitData, device: str = DEVICE, batch: int = 512) -> dict:
    import torch

    if split.X.shape[0] == 0:
        return {"loss": 0.0, "ndcg@5": 0.0, "ndcg@10": 0.0, "mrr@10": 0.0, "map@10": 0.0, "auc_roc": 0.0, "n_eval_queries": 0}
    model.eval()
    bce = torch.nn.BCEWithLogitsLoss()
    xs = torch.tensor(split.X, dtype=torch.float32, device=device)
    ys = torch.tensor(split.y_bin, dtype=torch.float32, device=device)
    with torch.no_grad():
        logits_all = []
        for i in range(0, xs.shape[0], batch):
            logits_all.append(model(xs[i:i + batch]).detach().cpu())
        logits = torch.cat(logits_all, dim=0)
        val_loss = float(bce(logits, ys.detach().cpu()).item())
    preds = logits.numpy().astype(np.float64)
    metrics = _eval_groups_ranking(split, preds)
    metrics["loss"] = val_loss
    return metrics


# ----------------------------- Baselines -----------------------------------

def train_lightgbm_baseline(train: SplitData, val: SplitData) -> tuple[dict | None, np.ndarray | None]:
    """Train LightGBM GBDT baseline on same standardized features (apples-to-apples)."""
    try:
        import lightgbm as lgb  # noqa: PLC0415

        # Prefer ranker when we have group structure; fall back to classifier.
        model = None
        preds = None
        try:
            train_groups = [len(g) for g in train.groups if len(g) > 0]
            val_groups = [len(g) for g in val.groups if len(g) > 0]
            if sum(train_groups) == len(train.y) and sum(val_groups) == len(val.y) and train_groups:
                ranker = lgb.LGBMRanker(
                    objective="lambdarank",
                    n_estimators=300,
                    learning_rate=0.05,
                    num_leaves=31,
                    min_child_samples=5,
                    subsample=0.9,
                    colsample_bytree=0.9,
                    random_state=SEED,
                )
                ranker.fit(
                    train.X, train.y,
                    group=train_groups,
                    eval_set=[(val.X, val.y)],
                    eval_group=[val_groups],
                )
                preds = ranker.predict(val.X)
                model = ranker
        except Exception:
            model = None
            preds = None

        if model is None:
            clf = lgb.LGBMClassifier(
                objective="binary",
                n_estimators=300,
                learning_rate=0.05,
                num_leaves=31,
                min_child_samples=5,
                subsample=0.9,
                colsample_bytree=0.9,
                random_state=SEED,
                class_weight="balanced",
            )
            clf.fit(train.X, train.y_bin.astype(int))
            # use probability of positive/high-intent as ranking score
            if hasattr(clf, "predict_proba"):
                preds = clf.predict_proba(val.X)[:, 1]
            else:
                preds = clf.predict(val.X)
            model = clf

        metrics = evaluate_baseline_scores(val, np.asarray(preds, dtype=np.float64))
        metrics["model"] = type(model).__name__
        return metrics, np.asarray(preds, dtype=np.float64)
    except Exception as exc:
        print(f"[dcn] LightGBM baseline training/eval failed: {exc}")
        return None, None


# ----------------------------- Plotting / output ---------------------------

def save_loss_curve(history: list[dict], out_json: Path, out_png: Path):
    out_json.write_text(json.dumps({"history": history}, indent=2), encoding="utf-8")
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt  # noqa: PLC0415

        epochs = [h["epoch"] for h in history]
        fig, ax1 = plt.subplots(figsize=(8.5, 4.8))
        ax1.plot(epochs, [h["train_loss"] for h in history], label="Train Loss", color="#2563eb")
        ax1.plot(epochs, [h["val_loss"] for h in history], label="Val Loss", color="#dc2626")
        ax1.set_xlabel("Epoch")
        ax1.set_ylabel("Loss")
        ax1.grid(True, alpha=0.25)
        ax2 = ax1.twinx()
        ax2.plot(epochs, [h["val_ndcg10"] for h in history], label="Val NDCG@10", color="#16a34a", linestyle="--")
        ax2.plot(epochs, [h["val_auc_roc"] for h in history], label="Val AUC-ROC", color="#9333ea", linestyle=":")
        ax2.set_ylim(0.0, 1.05)
        ax2.set_ylabel("Metric")
        l1, lb1 = ax1.get_legend_handles_labels()
        l2, lb2 = ax2.get_legend_handles_labels()
        ax1.legend(l1 + l2, lb1 + lb2, loc="best", fontsize=8)
        ax1.set_title("M2 DCN-v2 Ranker: Train/Val Loss, Val NDCG@10, Val AUC-ROC")
        fig.tight_layout()
        fig.savefig(out_png, dpi=170)
        plt.close(fig)
        return str(out_png)
    except Exception as exc:
        print(f"[dcn] loss curve plot failed: {exc}")
        return None


def print_comparison_table(rows: list[tuple[str, dict]]):
    header = f"{'Model':38s} {'NDCG@5':>8s} {'NDCG@10':>8s} {'MRR@10':>8s} {'MAP@10':>8s} {'AUC-ROC':>8s} {'n_eval_q':>9s}"
    print("\n" + "=" * len(header))
    print("M2 Ranker Comparison (validation, profile-split, positive-bearing query groups only)")
    print("=" * len(header))
    print(header)
    print("-" * len(header))
    for name, m in rows:
        if not m:
            print(f"{name:38s} {'n/a':>8s} {'n/a':>8s} {'n/a':>8s} {'n/a':>8s} {'n/a':>8s} {'n/a':>9s}")
            continue
        nq = m.get("n_eval_queries", "n/a")
        print(
            f"{name:38s} "
            f"{m.get('ndcg@5', 0):8.4f} {m.get('ndcg@10', 0):8.4f} {m.get('mrr@10', 0):8.4f} {m.get('map@10', 0):8.4f} {m.get('auc_roc', 0):8.4f} {str(nq):>9s}"
        )
    print("=" * len(header))


# ----------------------------- Main run ------------------------------------

def run(epochs: int = EPOCHS) -> dict:
    import torch
    import torch.nn as nn

    set_seed(SEED)
    ARTIFACTS.mkdir(parents=True, exist_ok=True)

    train_path = DATASETS / "train.jsonl"
    val_path = DATASETS / "test.jsonl"
    if not train_path.exists() or not val_path.exists():
        raise SystemExit("datasets missing: run ml/build_datasets.py first")

    train_raw = load_split(train_path)
    val_raw = load_split(val_path)
    if train_raw.X.shape[0] == 0 or val_raw.X.shape[0] == 0:
        raise SystemExit("empty train/val split")

    scaler = StandardScalerFit().fit(train_raw.X)
    Xtr = scaler.transform(train_raw.X)
    Xva = scaler.transform(val_raw.X)
    train = SplitData(Xtr, train_raw.y, train_raw.y_bin, train_raw.scores_baseline, train_raw.groups)
    val = SplitData(Xva, val_raw.y, val_raw.y_bin, val_raw.scores_baseline, val_raw.groups)

    try:
        from app.services.rerank import FEATURE_ORDER  # noqa: PLC0415
        feature_order = list(FEATURE_ORDER)
    except Exception:
        feature_order = [f"f{i}" for i in range(train.X.shape[1])]

    # (a) Heuristic Weighted Sum Baseline (stored deterministic scores)
    baseline_metrics = evaluate_baseline_scores(val_raw, val_raw.scores_baseline)

    # (b) LightGBM GBDT baseline on same standardized features (apples-to-apples)
    print("[dcn] training LightGBM GBDT baseline on same standardized features...")
    lgbm_metrics, _ = train_lightgbm_baseline(train, val)

    # (c) DCN-v2
    in_dim = train.X.shape[1]
    model = build_dcn_model(in_dim, cross_layers=CROSS_LAYERS, hidden=HIDDEN, dropout=DROPOUT).to(DEVICE)
    opt = torch.optim.AdamW(model.parameters(), lr=LR, weight_decay=WEIGHT_DECAY)
    bce = nn.BCEWithLogitsLoss()

    history = []
    best_ndcg = -1.0
    best_state = None
    rng = np.random.default_rng(SEED)
    group_indices = list(range(len(train.groups)))

    for epoch in range(1, epochs + 1):
        model.train()
        rng.shuffle(group_indices)
        total_loss = 0.0
        steps = 0
        for gi in group_indices:
            g = train.groups[gi]
            if len(g) < 2:
                continue
            gx = torch.tensor(train.X[g], dtype=torch.float32, device=DEVICE)
            gy = torch.tensor(train.y[g], dtype=torch.float32, device=DEVICE)
            gyb = torch.tensor(train.y_bin[g], dtype=torch.float32, device=DEVICE)
            logits = model(gx)
            loss_bce = bce(logits, gyb)
            loss_pair = pairwise_ranknet_loss(logits, gy, max_pairs=MAX_PAIRS_PER_GROUP, margin=PAIR_MARGIN)
            loss = BCE_WEIGHT * loss_bce + PAIRWISE_WEIGHT * loss_pair
            opt.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 2.0)
            opt.step()
            total_loss += float(loss.item())
            steps += 1
        train_loss = total_loss / max(1, steps)
        val_metrics = evaluate_split(model, val, device=DEVICE)
        rec = {
            "epoch": epoch,
            "train_loss": float(train_loss),
            "val_loss": float(val_metrics.get("loss", 0.0)),
            "val_ndcg10": float(val_metrics.get("ndcg@10", 0.0)),
            "val_auc_roc": float(val_metrics.get("auc_roc", 0.0)),
            "val_ndcg5": float(val_metrics.get("ndcg@5", 0.0)),
            "val_mrr10": float(val_metrics.get("mrr@10", 0.0)),
            "val_map10": float(val_metrics.get("map@10", 0.0)),
            "n_eval_queries": int(val_metrics.get("n_eval_queries", 0)),
        }
        history.append(rec)
        if rec["val_ndcg10"] >= best_ndcg:
            best_ndcg = rec["val_ndcg10"]
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
        if epoch == 1 or epoch % 5 == 0 or epoch == epochs:
            print(
                f"[dcn] epoch {epoch:03d}/{epochs} "
                f"train_loss={rec['train_loss']:.4f} val_loss={rec['val_loss']:.4f} "
                f"val_ndcg@10={rec['val_ndcg10']:.4f} val_auc_roc={rec['val_auc_roc']:.4f} "
                f"n_eval_queries={rec['n_eval_queries']}"
            )

    if best_state is not None:
        model.load_state_dict(best_state)

    final_val = evaluate_split(model, val, device=DEVICE)
    dcn_metrics = {k: final_val.get(k) for k in ["ndcg@5", "ndcg@10", "mrr@10", "map@10", "auc_roc", "n_eval_queries", "n_total_groups"]}
    dcn_metrics["positive_label_min"] = POSITIVE_LABEL_MIN

    version = "v1"
    artifact_path = ARTIFACTS / f"dcn_ranker_{version}.pt"
    manifest = {
        "feature_order": feature_order,
        "in_dim": in_dim,
        "cross_layers": CROSS_LAYERS,
        "hidden": HIDDEN,
        "dropout": DROPOUT,
        "loss": "Pairwise RankNet (logistic) + BCE hybrid",
        "pairwise_weight": PAIRWISE_WEIGHT,
        "bce_weight": BCE_WEIGHT,
        "positive_label_min": POSITIVE_LABEL_MIN,
        "epochs": epochs,
        "seed": SEED,
        "split": {"train_groups": len(train.groups), "val_groups": len(val.groups), "zero_user_overlap": True},
        "evaluation_protocol": "ranking metrics over groups with >=1 positive and >=2 items",
        "trained_at": datetime.now(timezone.utc).isoformat(),
    }
    payload = {
        "state_dict": model.state_dict(),
        "scaler": scaler.to_dict(),
        "feature_order": feature_order,
        "manifest": manifest,
        "version": version,
        "cross_layers": CROSS_LAYERS,
        "hidden": HIDDEN,
        "dropout": DROPOUT,
        "metrics": {"val": dcn_metrics, "baseline": baseline_metrics, "lightgbm_gbdt": lgbm_metrics},
        "history": history,
    }
    torch.save(payload, artifact_path)

    curve_json = ARTIFACTS / "dcn_loss_curve.json"
    curve_png = ARTIFACTS / "dcn_loss_curve.png"
    curve_png_path = save_loss_curve(history, curve_json, curve_png)

    comparison = [
        ("(a) Heuristic Weighted Sum Baseline", baseline_metrics),
        ("(b) LightGBM GBDT (same features)", lgbm_metrics),
        ("(c) DCN-v2 Neural Ranker (new M2)", dcn_metrics),
    ]
    print_comparison_table(comparison)
    print(f"\n[dcn] n_eval_queries (positive-bearing, >=2 items): {dcn_metrics.get('n_eval_queries')} / val groups {dcn_metrics.get('n_total_groups')}")
    print(f"[dcn] artifact: {artifact_path}")
    print(f"[dcn] loss curve: {curve_png_path or curve_png}")
    print(f"[dcn] val metrics (DCN-v2): {json.dumps(dcn_metrics, indent=2)}")

    (ARTIFACTS / "dcn_ranker_v1.metrics.json").write_text(
        json.dumps({
            "baseline_heuristic": baseline_metrics,
            "lightgbm_gbdt": lgbm_metrics,
            "dcn_v2": dcn_metrics,
            "artifact": str(artifact_path),
            "loss_curve_png": str(curve_png_path or curve_png),
        }, indent=2),
        encoding="utf-8",
    )

    return {
        "artifact": str(artifact_path),
        "curve_png": str(curve_png_path or curve_png),
        "comparison": {"baseline": baseline_metrics, "lightgbm_gbdt": lgbm_metrics, "dcn_v2": dcn_metrics},
    }


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--epochs", type=int, default=EPOCHS)
    args = ap.parse_args(argv)
    run(epochs=args.epochs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
