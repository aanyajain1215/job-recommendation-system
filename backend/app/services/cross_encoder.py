"""M0 cross-encoder reranker (research-grade, pairwise scoring).

Scores (profile_text, job_text) pairs for precise reranking of top-K candidates
retrieved by the bi-encoder. Supports base or domain-fine-tuned cross-encoder.

Kept clean and fast: batched inference, raw logits/probabilities exposed for
downstream ranker/calibration (no ad-hoc score fusion here).
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from app.core.config import get_settings

log = logging.getLogger(__name__)

ARTIFACT_DIR = Path(__file__).resolve().parents[2] / "ml" / "artifacts"


def _sigmoid(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64)
    # numerically stable sigmoid
    out = np.empty_like(x)
    pos = x >= 0
    neg = ~pos
    out[pos] = 1.0 / (1.0 + np.exp(-x[pos]))
    ex = np.exp(x[neg])
    out[neg] = ex / (1.0 + ex)
    return out.astype(np.float32)


class CrossEncoderReranker:
    def __init__(self, model_name: str, finetuned_path: str | None = None, batch_size: int = 16) -> None:
        self.model_name = model_name
        self.finetuned_path = (finetuned_path or "").strip()
        self.batch_size = max(1, int(batch_size))
        self._model = None
        self._resolved = self._resolve_model_path()
        log.info("Cross-encoder reranker active: %s", self._resolved)

    @staticmethod
    def _has_weights(path: Path) -> bool:
        return path.is_dir() and any(
            (path / name).exists() for name in ("model.safetensors", "pytorch_model.bin")
        )

    def _resolve_model_path(self) -> str:
        if not self.finetuned_path:
            return self.model_name
        for cand in (Path(self.finetuned_path), ARTIFACT_DIR / self.finetuned_path):
            if self._has_weights(cand):
                return str(cand)
        # Weights are git-ignored (large); a fresh clone has only the config files.
        log.warning(
            "Fine-tuned cross-encoder weights not found at %r; using base model %s. "
            "Run `python ml/train_cross_encoder_real.py` to produce them.",
            self.finetuned_path, self.model_name,
        )
        return self.model_name

    def _get_model(self):
        if self._model is None:
            from sentence_transformers import CrossEncoder  # noqa: PLC0415

            self._model = CrossEncoder(self._resolved)
        return self._model

    def score_pairs(self, pairs: Sequence[tuple[str, str]]) -> np.ndarray:
        """Raw cross-encoder logits/scores (higher = more relevant)."""
        if not pairs:
            return np.asarray([], dtype=np.float32)
        model = self._get_model()
        scores = model.predict(list(pairs), batch_size=self.batch_size, show_progress_bar=False)
        return np.asarray(scores, dtype=np.float32).reshape(-1)

    def score_pairs_detailed(self, pairs: Sequence[tuple[str, str]]) -> tuple[np.ndarray, np.ndarray]:
        """Return (logits, sigmoid_probabilities) for each pair."""
        logits = self.score_pairs(pairs)
        if logits.size == 0:
            return logits, logits
        return logits, _sigmoid(logits)

    def rerank(
        self,
        profile_text: str,
        jobs: Sequence[Any],
        job_texts: Sequence[str],
        top_k: int | None = None,
    ) -> list[tuple[int, float]]:
        """Return list of (original_index, cross_encoder_logit) sorted desc."""
        n = min(len(jobs), len(job_texts))
        if n == 0:
            return []
        k = n if top_k is None else min(max(1, int(top_k)), n)
        pairs = [(profile_text or " ", job_texts[i] or " ") for i in range(n)]
        scores = self.score_pairs(pairs)
        order = sorted(range(n), key=lambda i: (-float(scores[i]), i))
        return [(i, float(scores[i])) for i in order[:k]]


@lru_cache
def get_cross_encoder() -> CrossEncoderReranker:
    settings = get_settings()
    return CrossEncoderReranker(
        model_name=settings.cross_encoder_model,
        finetuned_path=getattr(settings, "cross_encoder_finetuned_path", ""),
        batch_size=getattr(settings, "cross_encoder_batch_size", 16),
    )


def reset_cache() -> None:
    get_cross_encoder.cache_clear()
