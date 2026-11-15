"""Embedding service - M0 research-grade bi-encoder (BGE-base, 768-d).

Supports base BAAI/bge-base-en-v1.5 or a domain-fine-tuned bi-encoder
(InfoNCE / MultipleNegativesRankingLoss on resume-JD pairs). No hashing
fallback: neural embeddings are required.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from app.core.config import get_settings

log = logging.getLogger(__name__)

ML_DATA_DIR = Path(__file__).resolve().parents[2] / "ml" / "data"
ARTIFACT_DIR = Path(__file__).resolve().parents[2] / "ml" / "artifacts"

EMBEDDING_DIM = 768


class Embedder:
    """Bi-encoder embedder producing 768-d vectors, L2-normalised."""

    def __init__(self, model_name: str, finetuned_path: str | None = None) -> None:
        self.model_name = model_name
        self.finetuned_path = (finetuned_path or "").strip()
        self.backend = "biencoder"
        self._model = None
        self._resolved = self._resolve_model_path()
        self.dim = EMBEDDING_DIM
        log.info("Embedding bi-encoder active: %s (dim=%d)", self._resolved, self.dim)

    def _resolve_model_path(self) -> str:
        p = Path(self.finetuned_path) if self.finetuned_path else None
        if p and p.exists():
            return str(p)
        # also try relative to backend/ml/artifacts
        if self.finetuned_path:
            cand = ARTIFACT_DIR / self.finetuned_path
            if cand.exists():
                return str(cand)
        return self.model_name

    def _get_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer  # noqa: PLC0415

            self._model = SentenceTransformer(self._resolved)
            # best-effort dim check
            try:
                d = self._model.get_sentence_embedding_dimension()
                if d and int(d) != EMBEDDING_DIM:
                    log.warning("Bi-encoder dimension %s != expected %s", d, EMBEDDING_DIM)
            except Exception:
                pass
        return self._model

    def encode(self, texts: list[str], batch_size: int = 32) -> np.ndarray:
        """Return an (n, 768) float32 matrix, L2-normalised rows."""
        texts = [t if t and t.strip() else " " for t in texts]
        model = self._get_model()
        vecs = model.encode(
            texts,
            batch_size=batch_size,
            normalize_embeddings=True,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        arr = np.asarray(vecs, dtype=np.float32)
        if arr.ndim == 1:
            arr = arr.reshape(1, -1)
        # enforce L2 norm for safety
        norms = np.linalg.norm(arr, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return (arr / norms).astype(np.float32)

    def encode_one(self, text: str) -> list[float]:
        return self.encode([text])[0].tolist()


@lru_cache
def get_embedder() -> Embedder:
    settings = get_settings()
    return Embedder(
        model_name=settings.embedding_model,
        finetuned_path=getattr(settings, "embedding_finetuned_path", ""),
    )


# ---------------------------------------------------------------------------
# Document builders (shared by backfill + live scoring)
# ---------------------------------------------------------------------------

def build_profile_text(
    headline: str | None,
    bio: str | None,
    skill_names: list[str],
    target_family: str | None = None,
    project_blurb: str | None = None,
) -> str:
    parts = [p for p in (headline, bio) if p]
    if skill_names:
        parts.append("Skills: " + ", ".join(skill_names))
    if target_family:
        parts.append(f"Target role: {target_family}")
    if project_blurb:
        parts.append(project_blurb)
    return " \n ".join(parts).strip()


def build_job_text(
    title: str,
    requirements: str | None,
    description: str | None,
    required_skills: list[str],
) -> str:
    parts = [f"{title} {title} {title}"]
    if requirements:
        parts.append(f"{requirements} {requirements}")
    if description:
        parts.append(description)
    if required_skills:
        tripled = [s for s in required_skills for _ in range(3)]
        parts.append(" ".join(tripled))
    return " \n ".join(p for p in parts if p).strip()


# ---------------------------------------------------------------------------
# Persistence helpers (invalidate-on-write, recompute-on-read)
# ---------------------------------------------------------------------------

def ensure_profile_embedding(profile: Any) -> bool:
    if profile.embedding is not None and profile.embedding_updated_at is not None:
        if profile.updated_at is not None and profile.embedding_updated_at >= profile.updated_at:
            return False
    text = build_profile_text(
        headline=profile.headline,
        bio=profile.bio,
        skill_names=[
            ps.skill.name
            for ps in (profile.skills or [])
            if ps.skill is not None and ps.skill.name
        ],
        target_family=(
            profile.target_family.name
            if getattr(profile, "target_family", None) is not None
            else None
        ),
        project_blurb=None,
    )
    profile.embedding = get_embedder().encode_one(text)
    profile.embedding_updated_at = datetime.now(timezone.utc)
    return True


def _job_is_stale(job: Any) -> bool:
    if job.embedding is None or job.embedding_updated_at is None:
        return True
    return job.updated_at is not None and job.embedding_updated_at < job.updated_at


def ensure_job_embedding(job: Any) -> bool:
    if not _job_is_stale(job):
        return False
    ensure_job_embeddings([job])
    return True


def ensure_job_embeddings(jobs: Iterable[Any]) -> None:
    stale = [job for job in jobs if _job_is_stale(job)]
    if not stale:
        return
    texts = [
        build_job_text(
            title=job.title,
            requirements=job.requirements,
            description=job.description,
            required_skills=[
                js.skill.name
                for js in (job.skills or [])
                if js.skill is not None and js.skill.name and js.is_required
            ],
        )
        for job in stale
    ]
    vectors = get_embedder().encode(texts)
    now = datetime.now(timezone.utc)
    for job, vec in zip(stale, vectors, strict=True):
        job.embedding = vec.tolist()
        job.embedding_updated_at = now


def invalidate_profile_embedding(profile: Any) -> None:
    profile.embedding = None
    profile.embedding_updated_at = None


def invalidate_job_embedding(job: Any) -> None:
    job.embedding = None
    job.embedding_updated_at = None


# ---------------------------------------------------------------------------
# FX normalisation (plan §6 SalaryMatch)
# ---------------------------------------------------------------------------

@lru_cache
def fx_rates() -> dict[str, float]:
    path = ML_DATA_DIR / "fx_rates.yaml"
    rates: dict[str, float] = {"USD": 1.0}
    if path.exists():
        try:
            import yaml  # noqa: PLC0415

            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if isinstance(data, dict):
                for code, rate in data.items():
                    if isinstance(rate, (int, float)) and float(rate) > 0:
                        rates[str(code).upper()] = float(rate)
        except Exception:
            log.exception("Failed to read fx_rates.yaml; using USD-only anchor")
    return rates


def to_usd(amount: int | float, currency: str | None) -> float | None:
    if amount is None:
        return None
    code = (currency or "USD").upper()
    rate = fx_rates().get(code)
    if rate is None:
        return None
    return float(amount) * rate
