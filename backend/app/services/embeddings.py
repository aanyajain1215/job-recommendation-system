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

import hashlib
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

def compute_content_hash(text: str) -> str:
    """Return SHA-256 hex digest of the canonical text document."""
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def is_compatible_embedding(obj_a: Any, obj_b: Any) -> bool:
    """Verify that two objects share the identical embedding backend, model and dimension."""
    if getattr(obj_a, "embedding", None) is None or getattr(obj_b, "embedding", None) is None:
        return False
    backend_a = getattr(obj_a, "embedding_backend", None)
    backend_b = getattr(obj_b, "embedding_backend", None)
    if not backend_a or not backend_b or backend_a != backend_b:
        return False
    model_a = getattr(obj_a, "embedding_model", None)
    model_b = getattr(obj_b, "embedding_model", None)
    if not model_a or not model_b or model_a != model_b:
        return False
    dim_a = getattr(obj_a, "embedding_dimension", None)
    dim_b = getattr(obj_b, "embedding_dimension", None)
    if dim_a is not None and dim_b is not None and dim_a != dim_b:
        return False
    return True


class Embedder:
    """Normalises text and produces 384-d vectors via the configured backend with full provenance."""

    def __init__(self, backend: str = "auto", model_name: str = "all-MiniLM-L6-v2") -> None:
        self._model = None
        self._hashing = None
        self.model_name = model_name
        self.version = "v1"
        self.dimension = EMBEDDING_DIM
        self.backend = self._resolve_backend(backend, model_name)
        log.info("Embedding backend active: %s (model=%s, dim=%d)", self.backend, self.model_name, self.dimension)

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
# Persistence helpers with provenance tracking (plan §4/§13, Phase 1.3)
# ---------------------------------------------------------------------------

def ensure_profile_embedding(profile: Any, embedder: Embedder | None = None) -> bool:
    """Compute+store profile.embedding with full provenance. Returns True if recomputed."""
    if embedder is None:
        embedder = get_embedder()

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
    content_hash = compute_content_hash(text)

    if (
        profile.embedding is not None
        and profile.embedding_updated_at is not None
        and getattr(profile, "embedding_backend", None) == embedder.backend
        and getattr(profile, "embedding_model", None) == embedder.model_name
        and getattr(profile, "embedding_content_hash", None) == content_hash
    ):
        if profile.updated_at is None or profile.embedding_updated_at >= profile.updated_at:
            return False

    vec = embedder.encode_one(text)
    now = datetime.now(timezone.utc)
    profile.embedding = vec
    profile.embedding_backend = embedder.backend
    profile.embedding_model = embedder.model_name
    profile.embedding_version = embedder.version
    profile.embedding_dimension = embedder.dimension
    profile.embedding_content_hash = content_hash
    profile.embedding_updated_at = now
    return True


def _job_is_stale(job: Any, embedder: Embedder, content_hash: str) -> bool:
    if (
        job.embedding is None
        or job.embedding_updated_at is None
        or getattr(job, "embedding_backend", None) != embedder.backend
        or getattr(job, "embedding_model", None) != embedder.model_name
        or getattr(job, "embedding_content_hash", None) != content_hash
    ):
        return True
    return job.updated_at is not None and job.embedding_updated_at < job.updated_at


def ensure_job_embedding(job: Any, embedder: Embedder | None = None) -> bool:
    """Compute+store job.embedding if null or stale. Returns True if recomputed."""
    if embedder is None:
        embedder = get_embedder()
    text = build_job_text(
        title=job.title,
        requirements=job.requirements,
        description=job.description,
        required_skills=[
            js.skill.name
            for js in (job.skills or [])
            if js.skill is not None and js.skill.name and js.is_required
        ],
    )
    content_hash = compute_content_hash(text)
    if not _job_is_stale(job, embedder, content_hash):
        return False
    ensure_job_embeddings([job], embedder=embedder)
    return True


def ensure_job_embeddings(jobs: Iterable[Any], embedder: Embedder | None = None) -> None:
    """Batch recompute for a feed request with provenance."""
    if embedder is None:
        embedder = get_embedder()

    job_entries = []
    for job in jobs:
        text = build_job_text(
            title=job.title,
            requirements=job.requirements,
            description=job.description,
            required_skills=[
                js.skill.name
                for js in (job.skills or [])
                if js.skill is not None and js.skill.name and js.is_required
            ],
        )
        chash = compute_content_hash(text)
        if _job_is_stale(job, embedder, chash):
            job_entries.append((job, text, chash))

    if not job_entries:
        return

    vectors = embedder.encode([e[1] for e in job_entries])
    now = datetime.now(timezone.utc)
    for (job, _, chash), vec in zip(job_entries, vectors, strict=True):
        job.embedding = vec.tolist()
        job.embedding_backend = embedder.backend
        job.embedding_model = embedder.model_name
        job.embedding_version = embedder.version
        job.embedding_dimension = embedder.dimension
        job.embedding_content_hash = chash
        job.embedding_updated_at = now


def build_skill_text(name: str, category: str | None = None) -> str:
    return f"{name} ({category})" if category else name


def ensure_skill_embeddings(skills: Iterable[Any], embedder: Embedder | None = None) -> None:
    """Batch compute skill embeddings with provenance."""
    if embedder is None:
        embedder = get_embedder()

    stale_skills = []
    for sk in skills:
        text = build_skill_text(sk.name, sk.category)
        chash = compute_content_hash(text)
        if (
            sk.embedding is None
            or sk.embedding_updated_at is None
            or getattr(sk, "embedding_backend", None) != embedder.backend
            or getattr(sk, "embedding_model", None) != embedder.model_name
            or getattr(sk, "embedding_content_hash", None) != chash
        ):
            stale_skills.append((sk, text, chash))

    if not stale_skills:
        return

    vectors = embedder.encode([s[1] for s in stale_skills])
    now = datetime.now(timezone.utc)
    for (sk, _, chash), vec in zip(stale_skills, vectors, strict=True):
        sk.embedding = vec.tolist()
        sk.embedding_backend = embedder.backend
        sk.embedding_model = embedder.model_name
        sk.embedding_version = embedder.version
        sk.embedding_dimension = embedder.dimension
        sk.embedding_content_hash = chash
        sk.embedding_updated_at = now


def invalidate_profile_embedding(profile: Any) -> None:
    """Call on any profile/skills write so the next read re-embeds (plan §4)."""
    profile.embedding = None
    profile.embedding_backend = None
    profile.embedding_model = None
    profile.embedding_version = None
    profile.embedding_dimension = None
    profile.embedding_content_hash = None
    profile.embedding_updated_at = None


def invalidate_job_embedding(job: Any) -> None:
    job.embedding = None
    job.embedding_backend = None
    job.embedding_model = None
    job.embedding_version = None
    job.embedding_dimension = None
    job.embedding_content_hash = None
    job.embedding_updated_at = None


def invalidate_skill_embedding(skill: Any) -> None:
    skill.embedding = None
    skill.embedding_backend = None
    skill.embedding_model = None
    skill.embedding_version = None
    skill.embedding_dimension = None
    skill.embedding_content_hash = None
    skill.embedding_updated_at = None


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
