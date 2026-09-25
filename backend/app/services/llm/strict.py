"""LLM_STRICT trial mode (temporary): surface AI failures instead of degrading.

The routes in this codebase normally fall back to deterministic paths
(FTS parse, template explanations, heuristic resume parsing) whenever the
LLM is missing or fails.  That is correct production behaviour — but it
makes it impossible to *see* which features actually work with the LLM.

With ``LLM_STRICT=true`` every such decision point calls ``strict_bail``,
which raises :class:`LlmStrictError`; ``app.main`` maps it to HTTP 502
with the reason, so the UI shows an explicit "AI failure" instead of a
silently-heuristic answer.  Set ``LLM_STRICT=false`` to restore normal
graceful degradation.
"""

from __future__ import annotations

from app.core.config import get_settings


class LlmStrictError(RuntimeError):
    """LLM_STRICT=true and an AI path would otherwise fall back silently."""


def strict_bail(route: str, reason: str) -> None:
    """Raise in strict mode; no-op otherwise (normal fallback continues)."""
    if get_settings().llm_strict:
        raise LlmStrictError(f"{route}: {reason}")
