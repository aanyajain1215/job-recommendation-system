"""Real labelled data for M0: the Resume–Job-Description Fit dataset.

Source: https://huggingface.co/datasets/cnamuangtoun/resume-job-description-fit
Each row is a real (resume text, job description text) pair with a human label:
"No Fit" / "Potential Fit" / "Good Fit".  This replaces the synthetic
(`ml/ground_truth.py`-derived) pairs as the training signal for the
cross-encoder.

The dataset is downloaded once into `ml/data/external/resume_jd_fit/` (git-
ignored) and every later run reads the local copy.  All Hugging Face caches
are kept inside `backend/.cache/` so nothing is written outside the project.

Splits produced here:
  train / val  - carved from the dataset's own train split, grouped by job
                 description so no job appears in both
  test         - the dataset's own test split, untouched (its jobs never
                 appear in train; its resumes mostly do)
Leakage between the official train/test splits is measured and reported
(`overlap_report`) so evaluation can also be shown on the unseen subsets.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
CACHE_ROOT = BACKEND_ROOT / ".cache"
LOCAL_DIR = BACKEND_ROOT / "ml" / "data" / "external" / "resume_jd_fit"

HF_DATASET = "cnamuangtoun/resume-job-description-fit"
LABELS = {"No Fit": 0, "Potential Fit": 1, "Good Fit": 2}
# Soft relevance targets for the cross-encoder's BCE loss.
SOFT_TARGET = {0: 0.0, 1: 0.5, 2: 1.0}


def use_project_cache() -> None:
    """Point every HF / torch cache at backend/.cache (call before imports)."""
    os.environ.setdefault("HF_HOME", str(CACHE_ROOT / "huggingface"))
    os.environ.setdefault("TORCH_HOME", str(CACHE_ROOT / "torch"))


def text_key(text: str) -> str:
    norm = " ".join((text or "").split()).lower()
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()


def _to_rows(split) -> list[dict]:
    rows = []
    for r in split:
        label_raw = r["label"]
        if isinstance(label_raw, str):
            label = LABELS[label_raw.strip()]
        else:  # ClassLabel-encoded
            names = split.features["label"].names
            label = LABELS[names[int(label_raw)]]
        resume = (r["resume_text"] or "").strip()
        jd = (r["job_description_text"] or "").strip()
        if resume and jd:
            rows.append({"resume_text": resume, "job_text": jd, "label": label})
    return rows


def download() -> dict[str, Path]:
    """Fetch the dataset once and store it as JSONL under LOCAL_DIR."""
    paths = {s: LOCAL_DIR / f"{s}.jsonl" for s in ("train", "test")}
    if all(p.exists() for p in paths.values()):
        return paths
    use_project_cache()
    from datasets import load_dataset  # noqa: PLC0415

    ds = load_dataset(HF_DATASET, cache_dir=str(CACHE_ROOT / "huggingface" / "datasets"))
    LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    for split, path in paths.items():
        rows = _to_rows(ds[split])
        with path.open("w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    (LOCAL_DIR / "SOURCE.txt").write_text(
        f"Downloaded from https://huggingface.co/datasets/{HF_DATASET}\n"
        "Check the dataset card for licence terms before redistributing.\n",
        encoding="utf-8",
    )
    return paths


def _read(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def load_splits(val_ratio: float = 0.15, seed: int = 42) -> dict:
    """Return train/val/test rows plus an overlap (leakage) report."""
    paths = download()
    full_train = _read(paths["train"])
    test = _read(paths["test"])

    for row in full_train + test:
        row["resume_key"] = text_key(row["resume_text"])
        row["job_key"] = text_key(row["job_text"])

    # The official test split shares resumes with train but has NO job overlap,
    # i.e. it measures generalisation to unseen jobs. Validation mirrors that by
    # holding out whole jobs.
    jobs = sorted({r["job_key"] for r in full_train})
    random.Random(seed).shuffle(jobs)
    n_val = max(1, int(len(jobs) * val_ratio))
    val_keys = set(jobs[:n_val])
    train = [r for r in full_train if r["job_key"] not in val_keys]
    val = [r for r in full_train if r["job_key"] in val_keys]

    train_resumes = {r["resume_key"] for r in full_train}
    train_jobs = {r["job_key"] for r in full_train}
    for r in test:
        r["seen_resume"] = r["resume_key"] in train_resumes
        r["seen_job"] = r["job_key"] in train_jobs

    def _hist(rows):
        h = {name: 0 for name in LABELS}
        inv = {v: k for k, v in LABELS.items()}
        for r in rows:
            h[inv[r["label"]]] += 1
        return h

    overlap = {
        "test_rows": len(test),
        "test_rows_resume_seen_in_train": sum(r["seen_resume"] for r in test),
        "test_rows_job_seen_in_train": sum(r["seen_job"] for r in test),
        "test_rows_fully_unseen": sum(not r["seen_resume"] and not r["seen_job"] for r in test),
        "unique_resumes": {"train": len({r['resume_key'] for r in full_train}),
                           "test": len({r['resume_key'] for r in test})},
        "unique_jobs": {"train": len(train_jobs), "test": len({r['job_key'] for r in test})},
    }
    return {
        "train": train,
        "val": val,
        "test": test,
        "overlap_report": overlap,
        "label_histogram": {"train": _hist(train), "val": _hist(val), "test": _hist(test)},
        "source": f"https://huggingface.co/datasets/{HF_DATASET}",
    }
