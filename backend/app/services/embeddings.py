"""Embedding service (plan §4/§13).

Backs the previously-dead `Vector(384)` columns on profiles, jobs and skills.

Backend selection (settings.embedding_backend):
- "minilm" — sentence-transformers/all-MiniLM-L6-v2 (384-d, real semantics)
- "hashing" — deterministic sklearn HashingVectorizer fallback (no download,
  no network, stable across processes) so the API/tests always work offline
- "auto"   — MiniLM if importable, else hashing; the active backend is logged
             once so the demo never silently pretends to be semantic.

FX normalisation helper for salary scoring also lives here (plan §6/§20):
rates come from ml/data/fx_rates.yaml (curated, explicit — no live calls
inside scoring).
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

EMBEDDING_DIM = 384
ML_DATA_DIR = Path(__file__).resolve().parents[2] / "ml" / "data"


# ---------------------------------------------------------------------------
# Embedder
# ---------------------------------------------------------------------------

class Embedder:
    """Normalises text and produces 384-d vectors via the configured backend."""

    def __init__(self, backend: str = "auto", model_name: str = "all-MiniLM-L6-v2") -> None:
        self._model = None
        self._hashing = None
        self.backend = self._resolve_backend(backend, model_name)
        log.info("Embedding backend active: %s", self.backend)

    @staticmethod
    def _resolve_backend(backend: str, model_name: str) -> str:
        if backend == "hashing":
            return "hashing"
        try:
            if backend in ("auto", "minilm"):
                from sentence_transformers import SentenceTransformer  # noqa: PLC0415

                model = SentenceTransformer(model_name)
                Embedder._model_store = model  # type: ignore[attr-defined]
                return "minilm"
        except Exception as exc:  # ImportError, model download failure, etc.
            if backend == "minilm":
                log.warning("MiniLM requested but unavailable (%s); using hashing fallback.", exc)
            else:
                log.info("sentence-transformers unavailable (%s); using hashing fallback.", exc)
        return "hashing"

    def _get_model(self):
        if self._model is None:
            self._model = getattr(Embedder, "_model_store", None)
            if self._model is None:
                from sentence_transformers import SentenceTransformer  # noqa: PLC0415

                self._model = SentenceTransformer(
                    get_settings().embedding_model.split("/")[-1]
                )
        return self._model

    def _get_hashing(self):
        if self._hashing is None:
            from sklearn.feature_extraction.text import HashingVectorizer  # noqa: PLC0415

            self._hashing = HashingVectorizer(
                n_features=EMBEDDING_DIM,
                alternate_sign=False,
                norm="l2",
                ngram_range=(1, 2),
                stop_words="english",
            )
        return self._hashing

    def encode(self, texts: list[str]) -> np.ndarray:
        """Return an (n, 384) float32 matrix, L2-normalised rows."""
        texts = [t if t and t.strip() else " " for t in texts]
        if self.backend == "minilm":
            vecs = self._get_model().encode(
                texts, normalize_embeddings=True, show_progress_bar=False
            )
            return np.asarray(vecs, dtype=np.float32)
        return self._get_hashing().transform(texts).toarray().astype(np.float32)

    def encode_one(self, text: str) -> list[float]:
        return self.encode([text])[0].tolist()


@lru_cache
def get_embedder() -> Embedder:
    settings = get_settings()
    model_short = settings.embedding_model.split("/")[-1]
    return Embedder(backend=settings.embedding_backend, model_name=model_short)


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
    """plan §6: embed(headline + bio + canonical skills + target family + project blurb)."""
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
    """plan §6: embed(title×3 + requirements×2 + description + required skills×3)."""
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
    """Compute+store profile.embedding if null or stale vs updated_at. Returns True if recomputed."""
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
    """Compute+store job.embedding if null or stale. Returns True if recomputed."""
    if not _job_is_stale(job):
        return False
    ensure_job_embeddings([job])
    return True


def ensure_job_embeddings(jobs: Iterable[Any]) -> None:
    """Batch recompute for a feed request — one encode() call for all stale jobs."""
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
    """Call on any profile/skills write so the next read re-embeds (plan §4)."""
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
    """Currency -> USD rate from ml/data/fx_rates.yaml. USD = 1.0 anchor."""
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
        return None  # unknown currency: caller falls back to neutral prior
    return float(amount) * rate
