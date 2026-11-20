#!/usr/bin/env python
"""M0 cross-encoder fine-tuning on REAL labelled resume–job pairs.

Replaces the earlier run that trained on 45 synthetic positives
(`train_cross_encoder.py` + `embedding_pairs.jsonl`).  Data comes from the
public Resume–JD Fit dataset (see `ml/resume_jd_fit.py`): human-labelled
No Fit / Potential Fit / Good Fit pairs.

What this script does
  1. Downloads the dataset (once) into ml/data/external/resume_jd_fit/.
  2. Fine-tunes `cross-encoder/ms-marco-MiniLM-L-6-v2` with BCE on soft targets
     (No=0, Potential=0.5, Good=1), keeping the epoch with best validation loss.
  3. Evaluates on the untouched official test split, comparing:
        (a) BGE bi-encoder cosine      - the app's retrieval model, zero-shot
        (b) base MS-MARCO cross-encoder - zero-shot
        (c) fine-tuned cross-encoder    - this run
     Metrics: ROC-AUC (fit vs no-fit, good vs rest), Spearman, per-job NDCG@5/10
     (rank candidates for each job), and 3-class accuracy / macro-F1 with
     thresholds tuned on validation only.  Every test job is unseen in training,
     so the test numbers measure generalisation to new jobs.
  4. Saves the model to ml/artifacts/cross_encoder_finetuned/ and writes
     ml/artifacts/cross_encoder_training_report.json + loss curve.

    python ml/train_cross_encoder_real.py            # full run
    python ml/train_cross_encoder_real.py --epochs 1 --limit 400   # smoke test
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import sys
import time
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from ml.resume_jd_fit import CACHE_ROOT, SOFT_TARGET, load_splits, use_project_cache  # noqa: E402

use_project_cache()

ARTIFACTS = BACKEND_ROOT / "ml" / "artifacts"
OUT_DIR = ARTIFACTS / "cross_encoder_finetuned"
REPORT_PATH = ARTIFACTS / "cross_encoder_training_report.json"
CURVE_JSON_PATH = ARTIFACTS / "cross_encoder_loss_curve.json"
CURVE_PNG_PATH = ARTIFACTS / "cross_encoder_loss_curve.png"
CHECKPOINTS = CACHE_ROOT / "checkpoints" / "cross_encoder"


@dataclass
class TrainConfig:
    base_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    biencoder_model: str = "BAAI/bge-base-en-v1.5"
    epochs: int = 3
    batch_size: int = 16
    lr: float = 2e-5
    warmup_ratio: float = 0.1
    max_length: int = 512
    val_ratio: float = 0.15
    seed: int = 42
    use_amp: bool = True
    eval_batch_size: int = 8  # small: keeps GPU load/heat down during scoring
    limit: int = 0  # >0: subsample every split (smoke tests only)


# --------------------------------------------------------------------------
# Metrics
# --------------------------------------------------------------------------

def _ndcg_by_group(scores, labels, groups, k: int) -> tuple[float | None, int]:
    from sklearn.metrics import ndcg_score  # noqa: PLC0415

    by_group: dict[str, list[int]] = defaultdict(list)
    for i, g in enumerate(groups):
        by_group[g].append(i)
    vals = []
    for idx in by_group.values():
        ys = [labels[i] for i in idx]
        if len(idx) < 2 or len(set(ys)) < 2:
            continue  # nothing to rank
        vals.append(ndcg_score([ys], [[scores[i] for i in idx]], k=k))
    return (float(sum(vals) / len(vals)) if vals else None), len(vals)


def _tune_thresholds(scores, labels) -> tuple[float, float]:
    """Pick (t1, t2) maximising macro-F1 for No/Potential/Good on validation."""
    import numpy as np  # noqa: PLC0415
    from sklearn.metrics import f1_score  # noqa: PLC0415

    s = np.asarray(scores)
    qs = np.quantile(s, np.linspace(0.02, 0.98, 49))
    best = (-1.0, float(qs[0]), float(qs[-1]))
    for i, t1 in enumerate(qs):
        for t2 in qs[i:]:
            pred = np.where(s < t1, 0, np.where(s < t2, 1, 2))
            f1 = f1_score(labels, pred, average="macro")
            if f1 > best[0]:
                best = (f1, float(t1), float(t2))
    return best[1], best[2]


def evaluate(scores, rows, thresholds: tuple[float, float]) -> dict:
    import numpy as np  # noqa: PLC0415
    from scipy.stats import spearmanr  # noqa: PLC0415
    from sklearn.metrics import accuracy_score, f1_score, roc_auc_score  # noqa: PLC0415

    s = np.asarray(scores, dtype=float)
    y = np.asarray([r["label"] for r in rows])
    groups = [r["job_key"] for r in rows]
    t1, t2 = thresholds
    pred = np.where(s < t1, 0, np.where(s < t2, 1, 2))
    out = {"n": int(len(rows))}
    if len(set((y >= 1).tolist())) == 2:
        out["auc_fit_vs_nofit"] = round(float(roc_auc_score(y >= 1, s)), 4)
    if len(set((y == 2).tolist())) == 2:
        out["auc_good_vs_rest"] = round(float(roc_auc_score(y == 2, s)), 4)
    out["spearman"] = round(float(spearmanr(s, y).statistic), 4)
    for k in (5, 10):
        v, n = _ndcg_by_group(s.tolist(), y.tolist(), groups, k)
        out[f"ndcg@{k}_per_job"] = round(v, 4) if v is not None else None
    out["ndcg_jobs_evaluated"] = n
    out["accuracy_3class"] = round(float(accuracy_score(y, pred)), 4)
    out["macro_f1_3class"] = round(float(f1_score(y, pred, average="macro")), 4)
    return out


SCORE_CACHE = CACHE_ROOT / "eval_scores"


def evaluate_model(name: str, score_fn, val_rows, test_rows, cache: bool = False) -> dict:
    """Score val+test and compute metrics. With cache=True the raw scores are
    stored under backend/.cache/eval_scores so a crashed run can resume."""
    cache_path = SCORE_CACHE / f"{name}_{len(val_rows)}_{len(test_rows)}.json"
    if cache and cache_path.exists():
        saved = json.loads(cache_path.read_text(encoding="utf-8"))
        val_scores, test_scores, elapsed = saved["val"], saved["test"], saved["seconds"]
        print(f"[eval] {name}: reusing cached scores")
    else:
        t0 = time.perf_counter()
        val_scores = score_fn(val_rows)
        test_scores = score_fn(test_rows)
        elapsed = time.perf_counter() - t0
        if cache:
            SCORE_CACHE.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps({"val": val_scores, "test": test_scores, "seconds": elapsed}),
                                  encoding="utf-8")
    thresholds = _tune_thresholds(val_scores, [r["label"] for r in val_rows])
    result = {
        "test": evaluate(test_scores, test_rows, thresholds),
        "val": evaluate(val_scores, val_rows, thresholds),
        "thresholds_from_val": [round(t, 5) for t in thresholds],
        "scoring_seconds_val_plus_test": round(elapsed, 1),
    }
    print(f"[eval] {name}: {json.dumps(result['test'])}")
    return result


# --------------------------------------------------------------------------
# Scorers
# --------------------------------------------------------------------------

def cross_encoder_scorer(model, batch_size: int):
    def _score(rows):
        pairs = [(r["resume_text"], r["job_text"]) for r in rows]
        return [float(x) for x in model.predict(pairs, batch_size=batch_size, show_progress_bar=False)]
    return _score


def biencoder_scorer(model_name: str, batch_size: int):
    from sentence_transformers import SentenceTransformer  # noqa: PLC0415

    model = SentenceTransformer(model_name)
    model.max_seq_length = 512

    def _score(rows):
        texts = sorted({r["resume_text"] for r in rows} | {r["job_text"] for r in rows})
        emb = model.encode(texts, batch_size=batch_size, normalize_embeddings=True, show_progress_bar=False)
        index = {t: emb[i] for i, t in enumerate(texts)}
        return [float(index[r["resume_text"]] @ index[r["job_text"]]) for r in rows]
    return _score


# --------------------------------------------------------------------------
# Training
# --------------------------------------------------------------------------

def run(cfg: TrainConfig) -> dict:
    import numpy as np
    import torch
    from datasets import Dataset
    from sentence_transformers.cross_encoder import (
        CrossEncoder,
        CrossEncoderTrainer,
        CrossEncoderTrainingArguments,
    )
    from sentence_transformers.cross_encoder.losses import BinaryCrossEntropyLoss
    from transformers import TrainerCallback

    random.seed(cfg.seed)
    np.random.seed(cfg.seed)
    torch.manual_seed(cfg.seed)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"[setup] device={device}" + (f" ({torch.cuda.get_device_name(0)})" if device == "cuda" else ""))

    data = load_splits(val_ratio=cfg.val_ratio, seed=cfg.seed)
    train_rows, val_rows, test_rows = data["train"], data["val"], data["test"]
    if cfg.limit:
        rng = random.Random(cfg.seed)
        train_rows = rng.sample(train_rows, min(cfg.limit, len(train_rows)))
        val_rows = rng.sample(val_rows, min(cfg.limit // 4 or 1, len(val_rows)))
        test_rows = rng.sample(test_rows, min(cfg.limit // 2 or 1, len(test_rows)))
    print(f"[data] train={len(train_rows)} val={len(val_rows)} test={len(test_rows)}")
    print(f"[data] overlap: {json.dumps(data['overlap_report'])}")

    results: dict[str, dict] = {}

    # (a) bi-encoder baseline - what the app uses for retrieval today
    #     (scorer is built lazily so a cached result skips loading the model)
    _bi: dict = {}

    def _bge(rows):
        if "fn" not in _bi:
            _bi["fn"] = biencoder_scorer(cfg.biencoder_model, cfg.eval_batch_size)
        return _bi["fn"](rows)

    results["BGE bi-encoder cosine (zero-shot)"] = evaluate_model(
        "bge", _bge, val_rows, test_rows, cache=True)
    _bi.clear()
    torch.cuda.empty_cache() if device == "cuda" else None

    # (b) base cross-encoder, zero-shot
    model = CrossEncoder(cfg.base_model, num_labels=1, max_length=cfg.max_length, device=device)
    results["Base MS-MARCO cross-encoder (zero-shot)"] = evaluate_model(
        "base-ce", cross_encoder_scorer(model, cfg.eval_batch_size), val_rows, test_rows, cache=True)

    # (c) fine-tune
    def to_ds(items):
        return Dataset.from_dict({
            "sentence1": [r["resume_text"] for r in items],
            "sentence2": [r["job_text"] for r in items],
            "label": [SOFT_TARGET[r["label"]] for r in items],
        })

    train_log: list[dict] = []
    eval_log: list[dict] = []

    class LossCapture(TrainerCallback):
        def on_log(self, args, state, control, logs=None, **kwargs):  # noqa: ANN001, ANN201
            if logs and "loss" in logs:
                train_log.append({"step": int(state.global_step),
                                  "epoch": float(logs.get("epoch", state.epoch or 0.0)),
                                  "loss": float(logs["loss"])})

        def on_evaluate(self, args, state, control, metrics=None, **kwargs):  # noqa: ANN001, ANN201
            if metrics and "eval_loss" in metrics:
                eval_log.append({"step": int(state.global_step),
                                 "epoch": float(state.epoch or 0.0),
                                 "eval_loss": float(metrics["eval_loss"])})

    # micro-batches of <=8 with gradient accumulation: same effective batch,
    # lower peak GPU memory/power (the first full run crashed the laptop)
    micro = min(8, cfg.batch_size)
    accum = max(1, cfg.batch_size // micro)
    steps_per_epoch = max(1, -(-len(train_rows) // cfg.batch_size))
    args = CrossEncoderTrainingArguments(
        output_dir=str(CHECKPOINTS),
        num_train_epochs=float(cfg.epochs),
        per_device_train_batch_size=micro,
        gradient_accumulation_steps=accum,
        per_device_eval_batch_size=cfg.eval_batch_size,
        learning_rate=cfg.lr,
        warmup_steps=max(1, int(steps_per_epoch * cfg.epochs * cfg.warmup_ratio)),
        fp16=bool(cfg.use_amp and device == "cuda"),
        logging_steps=10,
        logging_first_step=True,
        eval_strategy="epoch",
        save_strategy="epoch",
        save_total_limit=1,
        load_best_model_at_end=True,
        metric_for_best_model="eval_loss",
        greater_is_better=False,
        report_to=[],
        seed=cfg.seed,
        data_seed=cfg.seed,
        dataloader_pin_memory=False,
    )
    trainer = CrossEncoderTrainer(
        model=model,
        args=args,
        train_dataset=to_ds(train_rows),
        eval_dataset=to_ds(val_rows),
        loss=BinaryCrossEntropyLoss(model=model),
        callbacks=[LossCapture()],
    )
    t0 = time.perf_counter()
    resume = any(CHECKPOINTS.glob("checkpoint-*")) if CHECKPOINTS.exists() else False
    if resume:
        print(f"[train] resuming from last checkpoint in {CHECKPOINTS}")
    train_out = trainer.train(resume_from_checkpoint=True if resume else None)
    train_seconds = time.perf_counter() - t0
    # trainer.state.log_history spans resumed runs too; prefer it over callbacks
    history = trainer.state.log_history or []
    if history:
        train_log = [{"step": int(h["step"]), "epoch": float(h.get("epoch", 0.0)), "loss": float(h["loss"])}
                     for h in history if "loss" in h]
        eval_log = [{"step": int(h["step"]), "epoch": float(h.get("epoch", 0.0)), "eval_loss": float(h["eval_loss"])}
                    for h in history if "eval_loss" in h]
    best_epoch = min(eval_log, key=lambda e: e["eval_loss"])["epoch"] if eval_log else None

    results["Fine-tuned cross-encoder (this run)"] = evaluate_model(
        "finetuned-ce", cross_encoder_scorer(model, cfg.eval_batch_size), val_rows, test_rows)

    if cfg.limit:
        shutil.rmtree(CHECKPOINTS, ignore_errors=True)
        print("[smoke] --limit set: skipping model/report save")
        return {"evaluation": results}

    # Save model (replaces the old synthetic-data model dir)
    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
    OUT_DIR.mkdir(parents=True)
    model.save_pretrained(str(OUT_DIR))
    shutil.rmtree(CHECKPOINTS, ignore_errors=True)

    # Curves (reuse the original plotting helper)
    from ml.train_cross_encoder import _plot_curves  # noqa: PLC0415

    CURVE_JSON_PATH.write_text(json.dumps({"train": train_log, "eval": eval_log}, indent=2), encoding="utf-8")
    png = _plot_curves(train_log, eval_log, CURVE_PNG_PATH)

    base = results["Base MS-MARCO cross-encoder (zero-shot)"]["test"]
    fine = results["Fine-tuned cross-encoder (this run)"]["test"]
    improvement = {
        k: round(fine[k] - base[k], 4)
        for k in fine
        if k != "n" and isinstance(fine.get(k), float) and isinstance(base.get(k), float)
    }

    report = {
        "model": "m0_cross_encoder",
        "data": {
            "kind": "real, human-labelled (resume, job description) pairs",
            "source": data["source"],
            "labels": "No Fit=0, Potential Fit=1, Good Fit=2 (soft targets 0 / 0.5 / 1)",
            "rows": {"train": len(train_rows), "val": len(val_rows), "test": len(test_rows)},
            "label_histogram": data["label_histogram"],
            "split": ("official test split untouched (all test jobs unseen in training); "
                      "validation carved from train by holding out whole jobs"),
            "train_test_overlap": data["overlap_report"],
            "replaces": "previous run trained on 45 synthetic positives from ml/ground_truth.py",
        },
        "base_model": cfg.base_model,
        "finetuned_path": str(OUT_DIR.relative_to(BACKEND_ROOT)).replace("\\", "/"),
        "method": "BinaryCrossEntropyLoss (soft graded targets) via CrossEncoderTrainer; best epoch by val loss",
        "config": asdict(cfg),
        "device": device,
        "train_seconds": round(train_seconds, 1),
        "best_epoch": best_epoch,
        "train_metrics": {k: v for k, v in (train_out.metrics or {}).items() if isinstance(v, (int, float))},
        "evaluation": results,
        "improvement_finetuned_vs_base_on_test": improvement,
        "loss_history": {"train": train_log, "eval": eval_log},
        "artifacts": {"model_dir": str(OUT_DIR), "loss_curve_png": png},
        "trained_at": datetime.now(timezone.utc).isoformat(),
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("evaluation", "improvement_finetuned_vs_base_on_test",
                                             "best_epoch", "train_seconds")}, indent=2))
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Fine-tune the cross-encoder on real Resume-JD Fit data")
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--batch-size", type=int, default=16)
    ap.add_argument("--lr", type=float, default=2e-5)
    ap.add_argument("--max-length", type=int, default=512)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--limit", type=int, default=0, help="subsample for a quick smoke test")
    ap.add_argument("--no-amp", action="store_true")
    a = ap.parse_args(argv)
    run(TrainConfig(epochs=a.epochs, batch_size=a.batch_size, lr=a.lr, max_length=a.max_length,
                    seed=a.seed, limit=a.limit, use_amp=not a.no_amp))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
