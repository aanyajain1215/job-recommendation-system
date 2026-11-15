#!/usr/bin/env python
"""M1 SkillGraph trainer (upgraded) — compatibility entrypoint.

M1 now uses a Graph Neural Network-style graph representation model:
**Heterogeneous Node2Vec** (biased random walks, p/q) over a directed
Skill-Role-Project heterogeneous graph, capturing multi-hop structural
dependencies (e.g. Python -> Pandas -> Data Analyst role) instead of only
flat window co-occurrence.

Implementation: ml/train_skill_graph_gnn.py
This module remains as a stable import/run shim for existing callers
(ml/train.py, ml/evaluate.py, tests) and provides compatible helpers
(load_artifact, cosine, run).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

ARTIFACTS = BACKEND_ROOT / "ml" / "artifacts"
GOLDEN_POSTINGS = BACKEND_ROOT / "ml" / "data" / "golden" / "postings.jsonl"
FAMILIES_YAML = BACKEND_ROOT / "ml" / "data" / "families.yaml"

DIM = 64
MIN_COUNT = 2
SEED = 42
WINDOW = 10
# Measured on the §21 golden pairs (centered vectors, τ=0.65):
#   epochs 20  → F1 0.54 (undertrained)
#   epochs 60  → F1 0.98  ← chosen
#   epochs 150 → F1 0.97 (saturated, slower)
EPOCHS = 60

# (d) curated skill lists — plan §6 M1(c)
CLUSTERS: list[list[str]] = [
    ["react", "vue.js", "next.js", "typescript", "javascript", "html", "css", "tailwind css"],
    ["python", "fastapi", "django", "node.js", "express", "postgresql", "redis"],
    ["java", "spring boot", "python", "git", "data structures", "system design", "unit testing"],
    ["docker", "kubernetes", "terraform", "aws", "ci/cd", "linux", "ansible", "github actions"],
    ["sql", "pandas", "numpy", "spark", "airflow", "tableau", "power bi", "statistics", "kafka"],
    ["pytorch", "tensorflow", "scikit-learn", "nlp", "computer vision", "hugging face",
     "machine learning", "deep learning", "mlops"],
    ["flutter", "react native", "swift", "kotlin"],
    ["python", "java", "git", "data structures", "system design", "unit testing"],
]


def _db_sentences() -> list[list[str]]:
    """(a) skill lists of published jobs."""
    try:
        from sqlalchemy import select  # noqa: PLC0415

        from app.core.db import SessionLocal  # noqa: PLC0415
        from app.models.enums import JobStatus  # noqa: PLC0415
        from app.models.job import Job  # noqa: PLC0415
        from app.models.skill import JobSkill  # noqa: PLC0415

        db = SessionLocal()
        try:
            rows = db.execute(
                select(JobSkill, Job)
                .join(Job, Job.id == JobSkill.job_id)
                .where(Job.status == JobStatus.PUBLISHED)
            ).all()
            per_job: dict[str, list[str]] = {}
            for job_skill, job in rows:
                if job_skill.skill is None or not job_skill.skill.name:
                    continue
                per_job.setdefault(str(job.id), []).append(
                    job_skill.skill.name.lower().strip()
                )
            return list(per_job.values())
        finally:
            db.close()
    except Exception as exc:  # noqa: BLE001 - training must run without DB
        print(f"[skill2vec] DB sentences skipped: {exc}", file=sys.stderr)
        return []


def _postings_sentences() -> list[list[str]]:
    """(b) golden posting skill lists."""
    import json as _json  # noqa: PLC0415

    if not GOLDEN_POSTINGS.exists():
        return []
    sentences: list[list[str]] = []
    with GOLDEN_POSTINGS.open(encoding="utf-8") as fh:
        for line in fh:
            row = _json.loads(line)
            # reuse the pipeline's own extraction so vocab matches serving
            from scripts.fetch_jobs_live import extract_skills, load_surface_pairs  # noqa: PLC0415

            skills = extract_skills(
                row.get("title", ""), row.get("description", ""), load_surface_pairs()
            )
            names = [name.lower().strip() for name, _required in skills]
            if names:
                sentences.append(names)
    return sentences


def _family_sentences() -> list[list[str]]:
    """(c) family core skills."""
    import yaml  # noqa: PLC0415

    if not FAMILIES_YAML.exists():
        return []
    data = yaml.safe_load(FAMILIES_YAML.read_text(encoding="utf-8")) or []
    return [
        [str(s).lower().strip() for s in (fam.get("core_skills") or [])]
        for fam in data
        if fam.get("core_skills")
    ]


def collect_sentences() -> list[list[str]]:
    sentences: list[list[str]] = []
    sentences.extend(_db_sentences())
    sentences.extend(_postings_sentences())
    sentences.extend(_family_sentences())
    # Each cluster is emitted as eight repeated full-list sentences plus every
    # within-cluster pair as its own sentence.  One occurrence per cluster
    # leaves skip-gram badly undertrained on a corpus this small (measured
    # transfer F1 0.15 on the §21 pairs); repeated unambiguous pair contexts
    # push true pairs over the 0.65 serving threshold while cross-cluster
    # pairs never share a context and stay far below it.
    for cluster in CLUSTERS:
        for _ in range(8):
            sentences.append(list(cluster))
        for i, a in enumerate(cluster):
            for b in cluster[i + 1:]:
                if a != b:
                    sentences.append([a, b])
    return [s for s in sentences if len(s) >= 2]


def train(sentences: Iterable[list[str]]) -> tuple[dict[str, list[float]], dict]:
    import numpy as np
    from gensim.models import Word2Vec  # noqa: PLC0415

    corpus = [list(s) for s in sentences]
    model = Word2Vec(
        sentences=corpus,
        vector_size=DIM,
        window=WINDOW,
        min_count=MIN_COUNT,
        sg=1,           # skip-gram
        seed=SEED,
        workers=1,      # determinism
        epochs=EPOCHS,
    )
    # All-but-the-top centering: a corpus this small collapses every vector
    # toward one shared direction (all pairwise cosines ≥ 0.65 → precision
    # 0.50 on the §21 pairs).  Subtracting the mean leaves only *relative*
    # co-occurrence, so true pairs stay over the 0.65 serving threshold and
    # cross-cluster pairs drop far below it.
    words = sorted(model.wv.index_to_key)
    matrix = np.vstack([model.wv[w] for w in words]).astype(np.float64)
    centered = matrix - matrix.mean(axis=0, keepdims=True)
    vectors = {
        word: centered[i].astype(float).tolist()
        for i, word in enumerate(words)
    }
    meta = {
        "dim": DIM,
        "min_count": MIN_COUNT,
        "seed": SEED,
        "window": WINDOW,
        "epochs": EPOCHS,
        "centered": True,
        "vocab_size": len(vectors),
        "sentence_count": len(corpus),
        "trained_at": datetime.now(timezone.utc).isoformat(),
    }
    return vectors, meta


def next_version() -> str:
    existing = sorted(ARTIFACTS.glob("skill2vec_v*.joblib"))
    highest = 0
    for path in existing:
        try:
            highest = max(highest, int(path.stem.split("_v")[-1]))
        except ValueError:
            continue
    return f"v{highest + 1}"


def load_artifact(path: Path | None = None) -> dict | None:
    """Newest M1 skill graph/GNN embedding payload or None (serving/eval helper)."""
    try:
        from ml.train_skill_graph_gnn import load_artifact as _load  # noqa: PLC0415

        return _load(path)
    except Exception:
        import joblib  # noqa: PLC0415

        if path is None:
            candidates = sorted(ARTIFACTS.glob("skill2vec_v*.joblib"))
            if not candidates:
                return None
            path = candidates[-1]
        try:
            payload = joblib.load(path)
            if isinstance(payload, dict) and "vectors" in payload:
                return payload
        except Exception as exc:  # noqa: BLE001
            print(f"[skill2vec] artifact load failed: {exc}", file=sys.stderr)
        return None


def cosine(a: list[float], b: list[float]) -> float:
    try:
        from ml.train_skill_graph_gnn import cosine as _cos  # noqa: PLC0415

        return float(_cos(a, b))
    except Exception:
        dot = sum(x * y for x, y in zip(a, b))
        na = sum(x * x for x in a) ** 0.5
        nb = sum(y * y for y in b) ** 0.5
        if na <= 0 or nb <= 0:
            return 0.0
        return dot / (na * nb)


def run(register: bool = True) -> dict:
    """Train M1 heterogeneous Node2Vec GNN over directed Skill-Role-Project graph."""
    from ml.train_skill_graph_gnn import run as _run  # noqa: PLC0415

    return _run(register=register, include_db=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Train M1 skill2vec")
    parser.add_argument("--no-register", action="store_true",
                        help="skip model_registry write (artifact only)")
    args = parser.parse_args(argv)
    run(register=not args.no_register)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
