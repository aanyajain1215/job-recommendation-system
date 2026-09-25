"""LLM provider abstraction (plan §15).

Contract: `complete_json(schema, prompt, *, system, max_tokens, route) ->
(BaseModel, LlmUsage)` —
  * JSON only, markdown fences stripped,
  * exactly one repair turn when Pydantic validation fails
    (`settings.llm_max_repair_turns`),
  * TTL-bounded in-process cache (identical prompt -> identical answer,
    which is also what keeps runs deterministic),
  * one `llm_usage` row per real call (cost/quota guardrails),
  * `mark_flagged` lets validators quarantine a response after the fact.

OpenAI is the default provider; Gemini is retained behind the same
interface.  The provider is only constructed when a key is configured —
callers fall back to deterministic paths when `get_provider()` returns None.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from app.core.config import get_settings
from app.services.llm.strict import strict_bail

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# USD per 1M tokens (prompt, completion) — order-of-magnitude cost estimate.
# Unknown models report 0.0 rather than a fabricated number.
_PRICING: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1": (2.00, 8.00),
    "gpt-4.3": (0.0, 0.0),
    "gemini-1.5-flash": (0.075, 0.30),
    "gemini-1.5-pro": (1.25, 5.00),
}


class LlmUnavailable(RuntimeError):
    """No provider could be constructed (missing key/package)."""


@dataclass
class LlmUsage:
    provider: str = ""
    model: str = ""
    route: str = "generic"
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0
    cached: bool = False
    flagged: bool = False
    row_id: str | None = None          # llm_usage.id, for late flagging
    problems: list[str] = field(default_factory=list)

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    @property
    def cost_usd(self) -> float:
        prompt_rate, completion_rate = _PRICING.get(self.model, (0.0, 0.0))
        return round(
            self.prompt_tokens / 1_000_000 * prompt_rate
            + self.completion_tokens / 1_000_000 * completion_rate,
            6,
        )


class JsonProvider(Protocol):
    name: str
    model: str

    def complete_json(
        self,
        schema: type[T],
        prompt: str,
        *,
        system: str = "",
        max_tokens: int = 1500,
        route: str = "generic",
    ) -> tuple[T, LlmUsage]: ...


# ---------------------------------------------------------------------------
# Helpers: fence stripping, cache, usage logging
# ---------------------------------------------------------------------------

def strip_fences(raw: str) -> str:
    """Remove markdown code fences (tolerates unclosed fences too)."""
    text = (raw or "").strip()
    m = re.match(r"\A```[a-zA-Z0-9_-]*\s*\n?(.*?)\n?```\s*\Z", text, re.S)
    if m:
        return m.group(1).strip()
    if text.startswith("```"):
        text = re.sub(r"\A```[a-zA-Z0-9_-]*\s*", "", text)
        text = re.sub(r"\s*```\Z", "", text)
    return text.strip()


def _schema_hint(schema: type[BaseModel]) -> str:
    try:
        spec = json.dumps(schema.model_json_schema())
    except Exception:  # pragma: no cover - schema introspection is best effort
        spec = "{}"
    return (
        "Return ONE valid JSON object that validates against this JSON "
        f"Schema (additional fields are ignored):\n{spec}"
    )


_CACHE: dict[str, tuple[float, Any]] = {}


def _cache_key(provider: str, model: str, system: str, prompt: str) -> str:
    digest = hashlib.sha256()
    for part in (provider, model, system, prompt):
        digest.update(part.encode("utf-8"))
        digest.update(b"\x00")
    return digest.hexdigest()


def _cache_get(key: str) -> Any | None:
    settings = get_settings()
    hit = _CACHE.get(key)
    if hit is None:
        return None
    ts, value = hit
    if time.time() - ts > settings.llm_cache_ttl_seconds:
        _CACHE.pop(key, None)
        return None
    return value


def _cache_put(key: str, value: Any) -> None:
    settings = get_settings()
    if len(_CACHE) >= settings.llm_cache_max_entries:
        _CACHE.clear()  # simple bounded cache; correctness over cleverness
    _CACHE[key] = (time.time(), value)


def _cached_copy(usage: LlmUsage) -> LlmUsage:
    return LlmUsage(
        provider=usage.provider,
        model=usage.model,
        route=usage.route,
        prompt_tokens=0,
        completion_tokens=0,
        latency_ms=0,
        cached=True,
        flagged=False,
    )


def _log_usage(usage: LlmUsage) -> None:
    """Persist one llm_usage row (best effort — observability must not
    break the request path, and the LLM never writes SQL itself)."""
    try:
        from app.core.db import SessionLocal
        from app.models.ops import LlmUsage as LlmUsageRow

        with SessionLocal() as db:
            row = LlmUsageRow(
                route=usage.route[:80],
                provider=usage.provider[:40],
                model=usage.model[:80],
                prompt_tokens=usage.prompt_tokens,
                completion_tokens=usage.completion_tokens,
                latency_ms=usage.latency_ms,
                cached=usage.cached,
                flagged=usage.flagged,
            )
            db.add(row)
            db.commit()
            usage.row_id = str(row.id)
    except Exception:  # pragma: no cover - logging must never raise
        log.debug("Failed to persist llm_usage row", exc_info=True)


def mark_flagged(usage: LlmUsage, reason: str = "") -> None:
    """Called by `validators` consumers when a response fails its contract."""
    usage.flagged = True
    if reason:
        log.warning("LLM output flagged (%s/%s): %s", usage.route, usage.model, reason)
    if usage.row_id is None:
        return
    try:
        from app.core.db import SessionLocal
        from app.models.ops import LlmUsage as LlmUsageRow
        from sqlalchemy import update

        with SessionLocal() as db:
            db.execute(
                update(LlmUsageRow)
                .where(LlmUsageRow.id == usage.row_id)
                .values(flagged=True)
            )
            db.commit()
    except Exception:  # pragma: no cover
        log.debug("Failed to flag llm_usage row", exc_info=True)


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------

class _BaseProvider:
    """Shared complete_json flow: cache → chat → validate → repair → log."""

    name: str = "base"
    model: str = ""

    def _chat(self, messages: list[dict[str, str]], max_tokens: int) -> tuple[str, dict[str, int]]:
        raise NotImplementedError

    def complete_json(
        self,
        schema: type[T],
        prompt: str,
        *,
        system: str = "",
        max_tokens: int = 1500,
        route: str = "generic",
    ) -> tuple[T, LlmUsage]:
        settings = get_settings()
        key = _cache_key(self.name, self.model, system, prompt)
        hit = _cache_get(key)
        if hit is not None:
            parsed, usage = hit
            return parsed.model_copy(deep=True), _cached_copy(usage)

        full_prompt = f"{prompt}\n\n{_schema_hint(schema)}"
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": full_prompt})

        started = time.perf_counter()
        raw, tokens = self._chat(messages, max_tokens)

        try:
            parsed = schema.model_validate_json(strip_fences(raw))
        except (ValidationError, ValueError, json.JSONDecodeError) as exc:
            # exactly one repair turn (plan §15)
            repair_err = str(exc)[:1500]
            if settings.llm_max_repair_turns < 1:
                raise
            messages.append({"role": "assistant", "content": raw})
            messages.append(
                {
                    "role": "user",
                    "content": (
                        f"The JSON you returned failed validation:\n{repair_err}\n"
                        "Return the corrected JSON object only — no fences, no commentary."
                    ),
                }
            )
            raw, tokens = self._chat(messages, max_tokens)
            parsed = schema.model_validate_json(strip_fences(raw))  # raises on 2nd failure

        usage = LlmUsage(
            provider=self.name,
            model=self.model,
            route=route,
            prompt_tokens=tokens.get("prompt_tokens", 0),
            completion_tokens=tokens.get("completion_tokens", 0),
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
        _cache_put(key, (parsed, usage))
        _log_usage(usage)
        return parsed, usage


class OpenAiProvider(_BaseProvider):
    name = "openai"

    def __init__(self, *, api_key: str, model: str, base_url: str = "", timeout: int = 30) -> None:
        if not api_key:
            raise LlmUnavailable("openai_api_key is not configured")
        try:
            from openai import OpenAI  # imported lazily: optional dependency
        except ImportError as exc:  # pragma: no cover
            raise LlmUnavailable("openai package is not installed") from exc
        self._client = OpenAI(
            api_key=api_key,
            base_url=base_url or None,
            timeout=timeout,
        )
        self.model = model

    def _chat(self, messages: list[dict[str, str]], max_tokens: int) -> tuple[str, dict[str, int]]:
        response = self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=0,
        )
        raw = response.choices[0].message.content or ""
        usage = getattr(response, "usage", None)
        return raw, {
            "prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
            "completion_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
        }


class GeminiProvider(_BaseProvider):
    name = "gemini"

    def __init__(self, *, api_key: str, model: str, timeout: int = 30) -> None:
        if not api_key:
            raise LlmUnavailable("gemini_api_key is not configured")
        try:
            import google.generativeai as genai  # optional dependency
        except ImportError as exc:  # pragma: no cover
            raise LlmUnavailable("google-generativeai package is not installed") from exc
        genai.configure(api_key=api_key)
        self._model = genai.GenerativeModel(model)
        self.model = model
        self._timeout = timeout

    def _chat(self, messages: list[dict[str, str]], max_tokens: int) -> tuple[str, dict[str, int]]:
        # Gemini has no multi-turn chat in this thin wrapper; flatten to text
        # (repair turn appends its error text to the conversation list, which
        # flattening naturally includes).
        parts = [f"{m['role'].upper()}: {m['content']}" for m in messages]
        response = self._model.generate_content(
            "\n\n".join(parts),
            generation_config={"max_output_tokens": max_tokens, "temperature": 0},
            # Bound the call — the deprecated SDK otherwise waits forever on a
            # stalled/throttled response, so a parse could sit in "parsing"
            # with no failure to report (LLM_TIMEOUT_SECONDS, default 30).
            request_options={"timeout": self._timeout},
        )
        raw = response.text or ""
        meta = getattr(response, "usage_metadata", None)
        return raw, {
            "prompt_tokens": int(getattr(meta, "prompt_token_count", 0) or 0),
            "completion_tokens": int(getattr(meta, "candidate_token_count", 0) or 0),
        }


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def get_provider() -> JsonProvider | None:
    """Configured provider, or None when no key is present (callers then
    use their deterministic fallback — never a hard failure).

    With ``LLM_STRICT=true`` each None-return raises LlmStrictError first,
    so misconfiguration surfaces instead of degrading silently.
    """
    settings = get_settings()
    if not settings.llm_enabled:
        # §22 kill switch — LLM_ENABLED=false degrades every route.
        log.info("LLM disabled via settings.llm_enabled; deterministic fallbacks in use")
        strict_bail("provider", "LLM_ENABLED=false (kill switch)")
        return None
    provider = (settings.llm_provider or "openai").lower().strip()

    if provider == "gemini":
        model = settings.llm_model
        if model.startswith("gpt-"):
            # Config still carries an OpenAI model name — substitute a current
            # free-tier Gemini model (gemini-1.5-flash was retired by Google;
            # requesting it 404s and silently degrades to fallbacks).
            model = "gemini-2.5-flash"
        if not settings.gemini_api_key:
            strict_bail("provider", "GEMINI_API_KEY not configured")
            return None
        try:
            return GeminiProvider(
                api_key=settings.gemini_api_key,
                model=model,
                timeout=settings.llm_timeout_seconds,
            )
        except LlmUnavailable as exc:
            strict_bail("provider", f"Gemini provider unavailable: {exc}")
            log.warning("Gemini provider unavailable; deterministic fallbacks in use")
            return None

    # default: OpenAI
    if not settings.openai_api_key and not settings.gemini_api_key:
        strict_bail("provider", "no LLM API key configured (OPENAI_API_KEY / GEMINI_API_KEY)")
        return None
    if not settings.openai_api_key and settings.gemini_api_key:
        # key set for Gemini only — honour it over a missing OpenAI key
        try:
            return GeminiProvider(
                api_key=settings.gemini_api_key,
                model="gemini-2.5-flash",
                timeout=settings.llm_timeout_seconds,
            )
        except LlmUnavailable as exc:  # pragma: no cover
            strict_bail("provider", f"Gemini provider unavailable: {exc}")
            return None
    try:
        return OpenAiProvider(
            api_key=settings.openai_api_key,
            model=settings.llm_model,
            base_url=settings.openai_base_url,
            timeout=settings.llm_timeout_seconds,
        )
    except LlmUnavailable as exc:  # pragma: no cover
        strict_bail("provider", f"OpenAI provider unavailable: {exc}")
        log.warning("OpenAI provider unavailable; deterministic fallbacks in use")
        return None


def llm_available() -> bool:
    return get_provider() is not None
