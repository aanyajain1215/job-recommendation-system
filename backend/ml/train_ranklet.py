#!/usr/bin/env python
"""M2 ranklet trainer (plan §6 M2 / §17 / §21).

LightGBM LambdaRank over the 30-feature deterministic vector built by
`app.services.rerank.build_features` (identical at train and serve time),
graded labels from `ml/build_datasets.py`, groups = profile feeds, temporal
split manifest respected.

Artifacts:
    ml/artifacts/ranklet_v{N}.txt              model (Booster text format —
                                                `.lgb` is gitignored, `.txt`
                                                is not)
    ml/artifacts/ranklet_v{N}.manifest.json    feature_order + params +
                                                metrics (serving refuses to
                                                load on order mismatch)

Registration defaults to active=False — promotion happens in ml/train.py
only after the §21 gate (NDCG@10 ≥ deterministic baseline) passes, so a
weak model never changes live rankings.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

ARTIFACTS = BACKEND_ROOT / "ml" / "artifacts"
DATASETS = BACKEND_ROOT / "ml" / "datasets"

PARAMS = {
    "objective": "lambdarank",
    "metric": "ndcg",
    "ndcg_at": [5, 10],
    "learning_rate": 0.05,
    "num_leaves": 31,
    "min_data_in_leaf": 5,
    "feature_fraction": 0.9,
    "seed": 42,
    "deterministic": True,
    "num_threads": 1,
    "verbosity": -1,
}
NUM_BOOST_ROUND = 100


def load_dataset(path: Path) -> tuple[list[list[float]], list[int], list[int], list[dict]]:
    """Rows must be group-contiguous; returns X, y, group sizes, raw rows."""
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not rows:
        return [], [], [], []
    X: list[list[float]] = []
    y: list[int] = []
    meta: list[dict] = []
    groups: list[int] = []
    current_group: str | None = None
    size = 0
    for row in rows:
        if current_group is not None and row["profile_id"] != current_group:
            groups.append(size)
            size = 0
        current_group = row["profile_id"]
        X.append([float(v) for v in row["features"]])
        y.append(int(row["label"]))
        meta.append(row)
        size += 1
    if size:
        groups.append(size)
    assert sum(groups) == len(rows)
    return X, y, groups, meta


def _ranked_labels(labels: list[int], scores: list[float]) -> list[int]:
    order = sorted(range(len(labels)), key=lambda i: (-scores[i], i))
    return [labels[i] for i in order]


def group_ndcg_at_10(labels: list[int], scores: list[float]) -> float:
    from ml.metrics import ndcg_at_k  # noqa: PLC0415

    return ndcg_at_k(_ranked_labels(labels, scores), 10)


def evaluate_baselines(train_meta: list[dict], test_meta: list[dict],
                       test_scores: list[float]) -> dict:
    from ml.metrics import (  # noqa: PLC0415
        mrr_at_k,
        ndcg_at_k,
        precision_at_k,
    )

    # popularity = mean train label per job (global mean fallback)
    per_job: dict[str, list[int]] = defaultdict(list)
    for row in train_meta:
        per_job[row["job_id"]].append(row["label"])
    global_mean = (
        sum(l for vals in per_job.values() for l in vals)
        / max(1, sum(len(v) for v in per_job.values()))
    )

    by_group: dict[str, list[int]] = defaultdict(list)
    for i, row in enumerate(test_meta):
        by_group[row["profile_id"]].append(i)

    results: dict[str, list[float]] = {
        "ranklet": [], "deterministic": [], "popularity": [],
    }
    precisions: dict[str, list[float]] = {"ranklet": [], "deterministic": [], "popularity": []}
    mrrs: dict[str, list[float]] = {"ranklet": [], "deterministic": [], "popularity": []}

    for _pid, idxs in by_group.items():
        labels = [test_meta[i]["label"] for i in idxs]
        score_sets = {
            "ranklet": [test_scores[i] for i in idxs],
            "deterministic": [test_meta[i]["score"] for i in idxs],
            "popularity": [
                (sum(per_job[test_meta[i]["job_id"]]) / len(per_job[test_meta[i]["job_id"]]))
                if test_meta[i]["job_id"] in per_job
                else global_mean
                for i in idxs
            ],
        }
        for name, scores in score_sets.items():
            ranked = _ranked_labels(labels, scores)
            results[name].append(ndcg_at_k(ranked, 10))
            precisions[name].append(precision_at_k(ranked, 5))
            mrrs[name].append(mrr_at_k(ranked, 10))

    metrics = {}
    for name in results:
        n = max(1, len(results[name]))
        metrics[name] = {
            "ndcg_at_10": round(sum(results[name]) / n, 4),
            "precision_at_5": round(sum(precisions[name]) / n, 4),
            "mrr_at_10": round(sum(mrrs[name]) / n, 4),
        }
    return metrics


def next_version() -> str:
    highest = 0
    for path in ARTIFACTS.glob("ranklet_v*.txt"):
        try:
            highest = max(highest, int(path.stem.split("_v")[-1]))
        except ValueError:
            continue
    return f"v{highest + 1}"


def run(register: bool = True) -> dict:
    try:
        import lightgbm as lgb  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(f"lightgbm required for M2 training: {exc}")

    train_path = DATASETS / "train.jsonl"
    test_path = DATASETS / "test.jsonl"
    if not train_path.exists() or not test_path.exists():
        raise SystemExit("[ranklet] datasets missing — run ml/build_datasets.py first")

    X_train, y_train, groups_train, train_meta = load_dataset(train_path)
    X_test, y_test, _groups_test, test_meta = load_dataset(test_path)
    if not X_train or not X_test:
        raise SystemExit("[ranklet] empty dataset")

    # LightGBM 4.x refuses raw Python lists for Dataset/predict — go through
    # explicit ndarrays (float32 features, int32 labels).
    import numpy as np  # noqa: PLC0415

    X_train_np = np.asarray(X_train, dtype=np.float32)
    y_train_np = np.asarray(y_train, dtype=np.int32)
    X_test_np = np.asarray(X_test, dtype=np.float32)
    y_test_np = np.asarray(y_test, dtype=np.int32)

    dtrain = lgb.Dataset(X_train_np, label=y_train_np, group=groups_train, free_raw_data=False)
    valid = None
    if X_test:
        test_groups: list[int] = []
        current = None
        size = 0
        for row in test_meta:
            if current is not None and row["profile_id"] != current:
                test_groups.append(size)
                size = 0
            current = row["profile_id"]
            size += 1
        if size:
            test_groups.append(size)
        valid = lgb.Dataset(X_test_np, label=y_test_np, group=test_groups, reference=dtrain)

    booster = lgb.train(
        PARAMS,
        dtrain,
        num_boost_round=NUM_BOOST_ROUND,
        valid_sets=[valid] if valid else None,
        callbacks=[lgb.log_evaluation(0)],
    )

    test_scores = booster.predict(X_test_np) if len(X_test_np) else []
    baselines = evaluate_baselines(train_meta, test_meta, list(test_scores))
    gate_pass = (
        baselines["ranklet"]["ndcg_at_10"] >= baselines["deterministic"]["ndcg_at_10"]
    )

    from app.services.rerank import FEATURE_ORDER  # noqa: PLC0415

    version = next_version()
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    model_path = ARTIFACTS / f"ranklet_{version}.txt"
    booster.save_model(str(model_path))

    manifest = {
        "feature_order": FEATURE_ORDER,
        "params": PARAMS,
        "num_boost_round": NUM_BOOST_ROUND,
        "metrics": baselines,
        "gate_ndcg_vs_deterministic": bool(gate_pass),
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "train_rows": len(X_train),
        "test_rows": len(X_test),
    }
    manifest_path = ARTIFACTS / f"ranklet_{version}.manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    result = {
        "artifact": str(model_path),
        "manifest": str(manifest_path),
        "version": version,
        "metrics": baselines,
        "gate_pass": gate_pass,
    }

    if register:
        import ml.ml_registry as registry  # noqa: PLC0415

        row = registry.register(
            "ranklet",
            version,
            str(model_path.relative_to(BACKEND_ROOT)),
            baselines,
            promote=False,  # promoted only after §21 gates (ml/train.py)
        )
        result["registry"] = row

    print(json.dumps(result, indent=2))
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Train M2 LightGBM ranklet")
    parser.add_argument("--no-register", action="store_true")
    args = parser.parse_args(argv)
    run(register=not args.no_register)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
