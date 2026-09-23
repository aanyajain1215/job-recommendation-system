"""LLM layer (plan §15): providers, prompts, validators.

The LLM never assigns scores and never executes SQL.  It extracts and
polishes; the deterministic engine owns every number.  Every call goes
through `provider.complete_json` (schema-validated, one repair turn, TTL
cache, `llm_usage` row) and its output is checked by `validators` before a
caller may trust it.
"""

from app.services.llm.provider import (
    LlmUnavailable,
    LlmUsage,
    get_provider,
    llm_available,
    mark_flagged,
    strip_fences,
)

__all__ = [
    "LlmUnavailable",
    "LlmUsage",
    "get_provider",
    "llm_available",
    "mark_flagged",
    "strip_fences",
]
