"""LLM provider abstraction (plan §15).

Two contracts:

* ``complete_json(schema, prompt, *, system, max_tokens, route) ->
  (BaseModel, LlmUsage)`` — structured outputs for extraction routes:
    - native JSON mode where the endpoint supports it (``response_format``),
      plus the schema attached to the prompt,
    - markdown fences stripped, Pydantic validation,
    - exactly one repair turn when validation fails
      (``settings.llm_max_repair_turns``),
    - TTL-bounded in-process cache (identical prompt -> identical answer,
      which is also what keeps runs deterministic),
    - one ``llm_usage`` row per real call (cost/quota guardrails),
    - ``mark_flagged`` lets validators quarantine a response after the fact.

* ``chat_tools(messages, tools, ...) -> ToolTurn`` — one native
  function-calling turn, the primitive the Career Copilot agent loop
  (``app.services.agent``) is built on.

Every provider speaks the OpenAI Chat Completions wire format: OpenAI
itself, Gemini through Google's OpenAI-compatible endpoint, and local models
through Ollama.  The deprecated ``google-generativeai`` SDK is kept only as
an opt-in legacy transport (``GEMINI_TRANSPORT=sdk``, JSON routes only).

The provider is only constructed when configured — callers fall back to
deterministic paths when ``get_provider()`` returns None.
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

GEMINI_OPENAI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
OLLAMA_DEFAULT_BASE_URL = "http://host.docker.internal:11434/v1"

# USD per 1M tokens (prompt, completion) — order-of-magnitude cost estimate.
# Unknown models report 0.0 rather than a fabricated number.
_PRICING: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1-nano": (0.10, 0.40),
    "gpt-4.1": (2.00, 8.00),
    "gemini-1.5-flash": (0.075, 0.30),
    "gemini-1.5-pro": (1.25, 5.00),
    "gemini-2.5-flash": (0.30, 2.50),
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


@dataclass
class ToolCall:
    """One native function call requested by the model."""

    id: str
    name: str
    arguments: dict[str, Any]
    raw_arguments: str = ""
    parse_error: str | None = None
    # Provider-specific fields that must be echoed back verbatim — e.g.
    # Gemini 3's ``extra_content.google.thought_signature`` (omitting it on
    # the follow-up request is a 400 INVALID_ARGUMENT).
    extra_content: dict[str, Any] | None = None


@dataclass
class ToolTurn:
    """One assistant turn from ``chat_tools``: text and/or tool calls."""

    content: str
    tool_calls: list[ToolCall]
    usage: LlmUsage
    finish_reason: str = ""


def assistant_tool_message(turn: ToolTurn) -> dict[str, Any]:
    """The assistant message to append before the tool results, echoing each
    call exactly as the provider issued it (ids, raw arguments, signatures)."""
    calls = []
    for c in turn.tool_calls:
        entry: dict[str, Any] = {
            "id": c.id,
            "type": "function",
            "function": {"name": c.name, "arguments": c.raw_arguments or json.dumps(c.arguments)},
        }
        if c.extra_content:
            entry["extra_content"] = c.extra_content
        calls.append(entry)
    return {"role": "assistant", "content": turn.content or None, "tool_calls": calls}


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
        # evict the oldest entry rather than flushing the whole cache
        oldest = min(_CACHE.items(), key=lambda kv: kv[1][0])[0]
        _CACHE.pop(oldest, None)
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


def _usage_tokens(response: Any) -> dict[str, int]:
    usage = getattr(response, "usage", None)
    return {
        "prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
        "completion_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
    }


def _extra_content(tool_call: Any) -> dict[str, Any] | None:
    extra = getattr(tool_call, "model_extra", None) or {}
    value = extra.get("extra_content") if isinstance(extra, dict) else None
    return value if isinstance(value, dict) else None


def _is_bad_request(exc: Exception) -> bool:
    return getattr(exc, "status_code", None) == 400 or type(exc).__name__ == "BadRequestError"


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------

class _BaseProvider:
    """Shared complete_json flow: cache → chat → validate → repair → log."""

    name: str = "base"
    model: str = ""
    supports_tools: bool = False

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
        prompt_tokens = tokens.get("prompt_tokens", 0)
        completion_tokens = tokens.get("completion_tokens", 0)

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
            prompt_tokens += tokens.get("prompt_tokens", 0)
            completion_tokens += tokens.get("completion_tokens", 0)
            parsed = schema.model_validate_json(strip_fences(raw))  # raises on 2nd failure

        usage = LlmUsage(
            provider=self.name,
            model=self.model,
            route=route,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
        _cache_put(key, (parsed, usage))
        _log_usage(usage)
        return parsed, usage


class OpenAiProvider(_BaseProvider):
    """Any OpenAI-compatible Chat Completions endpoint.

    Serves OpenAI itself, Gemini (Google's OpenAI-compatible endpoint),
    Ollama, Groq, vLLM, ... — one code path for JSON mode *and* native tool
    calling.
    """

    name = "openai"
    supports_tools = True

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = "",
        timeout: int = 30,
        name: str = "openai",
        max_retries: int = 2,
    ) -> None:
        if not api_key:
            raise LlmUnavailable(f"{name} api key is not configured")
        try:
            from openai import OpenAI  # imported lazily: optional dependency
        except ImportError as exc:  # pragma: no cover
            raise LlmUnavailable("openai package is not installed") from exc
        # max_retries: the SDK retries 408/409/429/5xx with exponential
        # backoff + jitter and honours Retry-After — free tiers 429 often.
        self._client = OpenAI(
            api_key=api_key,
            base_url=base_url or None,
            timeout=timeout,
            max_retries=max_retries,
        )
        self.model = model
        self.name = name
        # Native JSON mode; switched off for this instance if an endpoint
        # rejects `response_format` (some compatible servers don't support it).
        self._json_mode = True

    def _chat(self, messages: list[dict[str, str]], max_tokens: int) -> tuple[str, dict[str, int]]:
        from app.core.resilience import retry_call

        def _do():
            kwargs: dict[str, Any] = {
                "model": self.model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": 0,
            }
            if self._json_mode:
                kwargs["response_format"] = {"type": "json_object"}
            try:
                response = self._client.chat.completions.create(**kwargs)
            except Exception as exc:  # noqa: BLE001 - narrowed below
                if self._json_mode and _is_bad_request(exc) and "response_format" in str(exc).lower():
                    log.info("%s rejected response_format; continuing without JSON mode", self.name)
                    self._json_mode = False
                    kwargs.pop("response_format", None)
                    response = self._client.chat.completions.create(**kwargs)
                else:
                    raise
            raw = response.choices[0].message.content or ""
            return raw, _usage_tokens(response)

        # retry transient/provider errors with backoff (timeouts/network/429/5xx)
        return retry_call(_do, attempts=2, base_delay=0.8, max_delay=3.0)

    def chat_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        max_tokens: int = 900,
        route: str = "agent",
        temperature: float = 0.2,
    ) -> ToolTurn:
        """One native tool-calling turn (never cached: conversations are stateful)."""
        started = time.perf_counter()
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        response = self._client.chat.completions.create(**kwargs)
        choice = response.choices[0]
        message = choice.message
        calls: list[ToolCall] = []
        for i, tc in enumerate(getattr(message, "tool_calls", None) or []):
            fn = getattr(tc, "function", None)
            if fn is None:
                continue
            raw_args = fn.arguments or "{}"
            err: str | None = None
            try:
                args = json.loads(strip_fences(raw_args) or "{}")
                if not isinstance(args, dict):
                    args, err = {}, "arguments must be a JSON object"
            except (json.JSONDecodeError, ValueError) as exc:
                args, err = {}, f"invalid JSON arguments: {exc}"
            calls.append(
                ToolCall(
                    id=getattr(tc, "id", None) or f"call_{i}",
                    name=fn.name,
                    arguments=args,
                    raw_arguments=raw_args,
                    parse_error=err,
                    extra_content=_extra_content(tc),
                )
            )
        tokens = _usage_tokens(response)
        usage = LlmUsage(
            provider=self.name,
            model=self.model,
            route=route,
            prompt_tokens=tokens["prompt_tokens"],
            completion_tokens=tokens["completion_tokens"],
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
        _log_usage(usage)
        return ToolTurn(
            content=message.content or "",
            tool_calls=calls,
            usage=usage,
            finish_reason=str(getattr(choice, "finish_reason", "") or ""),
        )


class GeminiProvider(_BaseProvider):
    """Legacy transport via the deprecated ``google-generativeai`` SDK.

    Opt-in only (``GEMINI_TRANSPORT=sdk``) and JSON routes only — the default
    Gemini path is the OpenAI-compatible endpoint, which also supports native
    tool calling for the agent.
    """

    name = "gemini"
    supports_tools = False

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
        from app.core.resilience import retry_call

        # Flatten to text (the repair turn appends its error text to the
        # conversation list, which flattening naturally includes).
        parts = [f"{m['role'].upper()}: {m['content']}" for m in messages]

        def _do():
            response = self._model.generate_content(
                "\n\n".join(parts),
                generation_config={
                    "max_output_tokens": max_tokens,
                    "temperature": 0,
                    "response_mime_type": "application/json",
                },
                # Bound the call — the SDK otherwise waits forever on a stalled
                # or throttled response (LLM_TIMEOUT_SECONDS).
                request_options={"timeout": self._timeout},
            )
            raw = response.text or ""
            meta = getattr(response, "usage_metadata", None)
            return raw, {
                "prompt_tokens": int(getattr(meta, "prompt_token_count", 0) or 0),
                "completion_tokens": int(getattr(meta, "candidates_token_count", 0) or 0),
            }

        # retry transient/provider errors with backoff (timeouts/network/429/5xx)
        return retry_call(_do, attempts=2, base_delay=0.8, max_delay=3.0)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def _gemini_model(settings: Any) -> str:
    model = settings.llm_model
    if not model or model.startswith("gpt-"):
        # Config still carries an OpenAI model name — substitute a current
        # free-tier Gemini model rather than 404-ing into fallbacks.
        return "gemini-flash-lite-latest"
    return model


def _build_gemini(settings: Any) -> _BaseProvider:
    model = _gemini_model(settings)
    if (settings.gemini_transport or "openai_compat").lower() == "sdk":
        return GeminiProvider(
            api_key=settings.gemini_api_key,
            model=model,
            timeout=settings.llm_timeout_seconds,
        )
    return OpenAiProvider(
        api_key=settings.gemini_api_key,
        model=model,
        base_url=GEMINI_OPENAI_BASE_URL,
        timeout=settings.llm_timeout_seconds,
        name="gemini",
        max_retries=settings.llm_max_retries,
    )


def get_provider() -> JsonProvider | None:
    """Configured provider, or None when not configured (callers then use
    their deterministic fallback — never a hard failure).

    ``LLM_PROVIDER``: ``openai`` (default), ``gemini`` or ``ollama`` (local
    models via Ollama's OpenAI-compatible API, no key needed).  With
    ``LLM_STRICT=true`` each None-return raises LlmStrictError first, so
    misconfiguration surfaces instead of degrading silently.
    """
    settings = get_settings()
    if not settings.llm_enabled:
        # §22 kill switch — LLM_ENABLED=false degrades every route.
        log.info("LLM disabled via settings.llm_enabled; deterministic fallbacks in use")
        strict_bail("provider", "LLM_ENABLED=false (kill switch)")
        return None
    provider = (settings.llm_provider or "openai").lower().strip()

    try:
        if provider == "ollama":
            return OpenAiProvider(
                api_key="ollama",  # Ollama ignores the key; the SDK requires one
                model=settings.llm_model if not settings.llm_model.startswith("gpt-") else "llama3.1",
                base_url=settings.openai_base_url or OLLAMA_DEFAULT_BASE_URL,
                timeout=settings.llm_timeout_seconds,
                name="ollama",
                max_retries=settings.llm_max_retries,
            )

        if provider == "gemini":
            if not settings.gemini_api_key:
                strict_bail("provider", "GEMINI_API_KEY not configured")
                return None
            return _build_gemini(settings)

        # default: OpenAI
        if not settings.openai_api_key and not settings.gemini_api_key:
            strict_bail("provider", "no LLM API key configured (OPENAI_API_KEY / GEMINI_API_KEY)")
            return None
        if not settings.openai_api_key and settings.gemini_api_key:
            # key set for Gemini only — honour it over a missing OpenAI key
            return _build_gemini(settings)
        return OpenAiProvider(
            api_key=settings.openai_api_key,
            model=settings.llm_model,
            base_url=settings.openai_base_url,
            timeout=settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,
        )
    except LlmUnavailable as exc:
        strict_bail("provider", f"{provider} provider unavailable: {exc}")
        log.warning("%s provider unavailable (%s); deterministic fallbacks in use", provider, exc)
        return None


def get_tool_provider() -> OpenAiProvider | None:
    """A provider capable of native tool calling (agent loop), or None."""
    provider = get_provider()
    if provider is not None and getattr(provider, "supports_tools", False):
        return provider  # type: ignore[return-value]
    return None


def llm_available() -> bool:
    return get_provider() is not None
