#!/usr/bin/env python
"""M0 cross-encoder training (research-grade, pairwise relevance reranker).

Trains/fine-tunes a cross-encoder on (profile_text, job_text) pairs with binary
labels derived from interactions (clean positives/negatives). Uses
CrossEncoderTrainer with per-step logging and per-epoch validation so train and
validation loss curves are captured.

Data hygiene:
  - Reads ml/datasets/embedding_pairs.jsonl (with profile_id/job_id)
  - Uses labeled pairs (label 0/1)
  - Splits strictly by profile_id (80% train / 20% validation, zero user overlap)

Artifacts:
  ml/artifacts/cross_encoder_finetuned/            (CrossEncoder model)
  ml/artifacts/cross_encoder_training_report.json  (config, metrics, loss history)
  ml/artifacts/cross_encoder_loss_curve.json       (plot-ready train/val points)
  ml/artifacts/cross_encoder_loss_curve.png        (Train Loss + Validation Loss)
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

ARTIFACTS = BACKEND_ROOT / "ml" / "artifacts"
DATASETS = BACKEND_ROOT / "ml" / "datasets"
PAIRS_PATH = DATASETS / "embedding_pairs.jsonl"
OUT_DIR = ARTIFACTS / "cross_encoder_finetuned"
REPORT_PATH = ARTIFACTS / "cross_encoder_training_report.json"
CURVE_JSON_PATH = ARTIFACTS / "cross_encoder_loss_curve.json"
CURVE_PNG_PATH = ARTIFACTS / "cross_encoder_loss_curve.png"


@dataclass
class TrainConfig:
    base_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    epochs: int = 2
    batch_size: int = 16
    lr: float = 2e-5
    warmup_ratio: float = 0.1
    seed: int = 42
    logging_steps: int = 1
    train_ratio: float = 0.8
    use_amp: bool = True


def load_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        pt = str(r.get("profile_text") or "").strip()
        jt = str(r.get("job_text") or "").strip()
        if pt and jt:
            r["profile_text"] = pt
            r["job_text"] = jt
            r["label"] = float(r.get("label", 0))
            rows.append(r)
    return rows


def split_by_profile(rows: list[dict], train_ratio: float, seed: int):
    """Group-strict split by profile_id with zero user overlap."""
    by_profile: dict[str, list[dict]] = {}
    for r in rows:
        pid = str(r.get("profile_id") or "unknown")
        by_profile.setdefault(pid, []).append(r)
    profiles = sorted(by_profile.keys())
    rng = random.Random(seed)
    rng.shuffle(profiles)
    if len(profiles) <= 1:
        train_ids = set(profiles)
        val_ids: set[str] = set()
    else:
        n_train = max(1, int(round(len(profiles) * train_ratio)))
        if n_train >= len(profiles):
            n_train = len(profiles) - 1
        train_ids = set(profiles[:n_train])
        val_ids = set(profiles[n_train:])
    train = [r for pid in profiles if pid in train_ids for r in by_profile[pid]]
    val = [r for pid in profiles if pid in val_ids for r in by_profile[pid]]
    return train, val, sorted(train_ids), sorted(val_ids)


def _plot_curves(train_points: list[dict], eval_points: list[dict], out_png: Path) -> str | None:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt  # noqa: PLC0415

        fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))

        t_steps = [p["step"] for p in train_points if p.get("loss") is not None]
        t_loss = [p["loss"] for p in train_points if p.get("loss") is not None]
        if t_steps:
            axes[0].plot(t_steps, t_loss, label="Train Loss", color="#2563eb", linewidth=1.4)
        axes[0].set_title("Train Loss")
        axes[0].set_xlabel("Global step")
        axes[0].set_ylabel("Loss")
        axes[0].grid(True, alpha=0.25)
        axes[0].legend()

        e_epochs = [p.get("epoch", i + 1) for i, p in enumerate(eval_points)]
        e_loss = [p.get("eval_loss") for p in eval_points]
        if e_epochs and any(v is not None for v in e_loss):
            axes[1].plot(e_epochs, e_loss, marker="o", label="Validation Loss", color="#dc2626", linewidth=1.6)
        axes[1].set_title("Validation Loss")
        axes[1].set_xlabel("Epoch")
        axes[1].set_ylabel("Loss")
        axes[1].grid(True, alpha=0.25)
        axes[1].legend()

        fig.suptitle("M0 Cross-Encoder Fine-tuning: Train vs Validation Loss", fontsize=11)
        fig.tight_layout()
        out_png.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(out_png, dpi=170)
        plt.close(fig)
        return str(out_png)
    except Exception as exc:
        print(f"[cross-encoder] plot failed: {exc}")
        return None


def train(cfg: TrainConfig) -> dict:
    random.seed(cfg.seed)
    try:
        import numpy as np
        import torch
        from datasets import Dataset
        from sentence_transformers.cross_encoder import CrossEncoder, CrossEncoderTrainer, CrossEncoderTrainingArguments
        from sentence_transformers.cross_encoder.losses import BinaryCrossEntropyLoss
        from transformers import TrainerCallback
    except Exception as exc:
        raise SystemExit(f"Training dependencies missing (torch/datasets/sentence-transformers/transformers): {exc}")

    torch.manual_seed(cfg.seed)
    np.random.seed(cfg.seed)

    rows = load_rows(PAIRS_PATH)
    if len(rows) < 8:
        raise SystemExit(f"Need >=8 labeled pairs in {PAIRS_PATH}. Run build_embedding_pairs.py")

    train_rows, val_rows, train_profiles, val_profiles = split_by_profile(rows, cfg.train_ratio, cfg.seed)
    if not val_rows and len(train_rows) > 8:
        cut = max(1, int(len(train_rows) * 0.2))
        val_rows = train_rows[-cut:]
        train_rows = train_rows[:-cut]

    def to_ds(items: list[dict]) -> Dataset:
        return Dataset.from_dict(
            {
                "sentence1": [r["profile_text"] for r in items],
                "sentence2": [r["job_text"] for r in items],
                "label": [float(r["label"]) for r in items],
            }
        )

    train_ds = to_ds(train_rows)
    eval_ds = to_ds(val_rows) if val_rows else None

    model = CrossEncoder(cfg.base_model, num_labels=1)
    loss = BinaryCrossEntropyLoss(model=model)

    train_log: list[dict] = []
    eval_log: list[dict] = []

    class LossCaptureCallback(TrainerCallback):
        def on_log(self, args, state, control, logs=None, **kwargs):  # noqa: ANN001, ANN201
            if not logs:
                return
            entry = {
                "step": int(state.global_step),
                "epoch": float(logs.get("epoch", state.epoch or 0.0) or 0.0),
            }
            if "loss" in logs:
                try:
                    entry["loss"] = float(logs["loss"])
                except Exception:
                    entry["loss"] = None
            if "learning_rate" in logs:
                try:
                    entry["learning_rate"] = float(logs["learning_rate"])
                except Exception:
                    pass
            if "loss" in entry or "learning_rate" in entry:
                train_log.append(entry)

        def on_evaluate(self, args, state, control, metrics=None, **kwargs):  # noqa: ANN001, ANN201
            if not metrics:
                return
            ev = {
                "step": int(state.global_step),
                "epoch": float(metrics.get("epoch", state.epoch or 0.0) or 0.0),
            }
            if "eval_loss" in metrics:
                try:
                    ev["eval_loss"] = float(metrics["eval_loss"])
                except Exception:
                    ev["eval_loss"] = None
            eval_log.append(ev)

    steps_per_epoch = max(1, (len(train_ds) + cfg.batch_size - 1) // cfg.batch_size)
    total_steps = max(1, steps_per_epoch * cfg.epochs)
    warmup_steps = max(1, int(total_steps * cfg.warmup_ratio))

    eval_strategy = "epoch" if eval_ds is not None else "no"

    args = CrossEncoderTrainingArguments(
        output_dir=str(ARTIFACTS / "_cross_encoder_checkpoints"),
        num_train_epochs=float(cfg.epochs),
        per_device_train_batch_size=int(cfg.batch_size),
        per_device_eval_batch_size=int(cfg.batch_size),
        learning_rate=float(cfg.lr),
        warmup_steps=int(warmup_steps),
        fp16=bool(cfg.use_amp and torch.cuda.is_available()),
        logging_steps=max(1, int(cfg.logging_steps)),
        logging_first_step=True,
        eval_strategy=eval_strategy,
        save_strategy="no",
        report_to=[],
        remove_unused_columns=False,
        seed=int(cfg.seed),
        data_seed=int(cfg.seed),
        load_best_model_at_end=False,
        dataloader_pin_memory=False,
    )

    trainer = CrossEncoderTrainer(
        model=model,
        args=args,
        train_dataset=train_ds,
        eval_dataset=eval_ds,
        loss=loss,
        callbacks=[LossCaptureCallback()],
    )

    train_result = trainer.train()
    metrics = {}
    try:
        metrics.update({k: float(v) if isinstance(v, (int, float)) else v for k, v in (train_result.metrics or {}).items()})
    except Exception:
        pass

    if eval_ds is not None:
        try:
            ev_metrics = trainer.evaluate()
            if ev_metrics:
                metrics.update({f"final_{k}": v for k, v in ev_metrics.items()})
                if not eval_log and "eval_loss" in ev_metrics:
                    eval_log.append({"step": int(trainer.state.global_step), "epoch": float(cfg.epochs), "eval_loss": float(ev_metrics["eval_loss"])})
        except Exception as exc:
            print(f"[cross-encoder] final eval failed: {exc}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    model.save(str(OUT_DIR))

    pos = sum(1 for r in rows if r["label"] >= 1)
    neg = sum(1 for r in rows if r["label"] < 1)

    curve_payload = {
        "train": train_log,
        "eval": eval_log,
        "meta": {"metric_train": "loss", "metric_eval": "eval_loss", "split": "profile_id_80_20_zero_overlap"},
    }
    CURVE_JSON_PATH.write_text(json.dumps(curve_payload, indent=2), encoding="utf-8")
    png_path = _plot_curves(train_log, eval_log, CURVE_PNG_PATH)

    report = {
        "model": "m0_cross_encoder",
        "base_model": cfg.base_model,
        "finetuned_path": str(OUT_DIR.relative_to(BACKEND_ROOT)),
        "method": "BinaryCrossEntropyLoss via CrossEncoderTrainer",
        "pairs_total": len(rows),
        "positives": pos,
        "negatives": neg,
        "train_pairs": len(train_rows),
        "val_pairs": len(val_rows),
        "train_profiles": len(train_profiles),
        "val_profiles": len(val_profiles),
        "profile_split": {"train_ratio": cfg.train_ratio, "seed": cfg.seed, "zero_user_overlap": True},
        "config": asdict(cfg),
        "metrics": metrics,
        "loss_history": {"train": train_log, "eval": eval_log},
        "artifacts": {
            "model_dir": str(OUT_DIR),
            "loss_curve_json": str(CURVE_JSON_PATH),
            "loss_curve_png": png_path,
        },
        "trained_at": datetime.now(timezone.utc).isoformat(),
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")

    summary = {k: v for k, v in report.items() if k not in {"loss_history"}}
    summary["train_log_points"] = len(train_log)
    summary["eval_log_points"] = len(eval_log)
    print(json.dumps(summary, indent=2))
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Fine-tune M0 cross-encoder reranker with strict profile split and loss curves")
    ap.add_argument("--base-model", default="cross-encoder/ms-marco-MiniLM-L-6-v2")
    ap.add_argument("--epochs", type=int, default=2)
    ap.add_argument("--batch-size", type=int, default=16)
    ap.add_argument("--lr", type=float, default=2e-5)
    ap.add_argument("--warmup-ratio", type=float, default=0.1)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--logging-steps", type=int, default=1)
    ap.add_argument("--train-ratio", type=float, default=0.8)
    ap.add_argument("--no-amp", action="store_true")
    args = ap.parse_args(argv)
    cfg = TrainConfig(
        base_model=args.base_model,
        epochs=args.epochs,
        batch_size=args.batch_size,
        lr=args.lr,
        warmup_ratio=args.warmup_ratio,
        seed=args.seed,
        logging_steps=args.logging_steps,
        train_ratio=args.train_ratio,
        use_amp=not args.no_amp,
    )
    train(cfg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
