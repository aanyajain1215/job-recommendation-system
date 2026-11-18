"""Per-caller sliding-window rate limits for LLM-backed endpoints.

Each Copilot turn or AI shortlist can fan out into several provider calls,
so these routes are capped per user (or per client IP when anonymous) to
protect quota and cost.  In-process state: with multiple workers each
worker enforces its own window, which is an acceptable upper bound for a
single-instance deploy (swap in Redis for horizontal scale).
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable

from fastapi import HTTPException, Request, status
from fastapi.security.utils import get_authorization_scheme_param

from app.core.config import get_settings

_WINDOW_SECONDS = 60.0
_hits: dict[str, deque[float]] = defaultdict(deque)
_lock = threading.Lock()


def _caller_key(request: Request) -> str:
    """User id from the bearer token when valid, else client IP."""
    scheme, token = get_authorization_scheme_param(request.headers.get("authorization"))
    if scheme.lower() == "bearer" and token:
        try:
            from app.core.security import decode_token

            sub = decode_token(token).get("sub")
            if sub:
                return f"user:{sub}"
        except Exception:  # noqa: BLE001 - invalid token: auth dependency rejects it
            pass
    client = request.client.host if request.client else "unknown"
    return f"ip:{client}"


def check(key: str, limit: int, now: float | None = None) -> float | None:
    """Record a hit; return seconds to wait when over ``limit``, else None."""
    if limit <= 0:
        return None
    now = time.monotonic() if now is None else now
    with _lock:
        q = _hits[key]
        while q and now - q[0] >= _WINDOW_SECONDS:
            q.popleft()
        if len(q) >= limit:
            return max(0.0, _WINDOW_SECONDS - (now - q[0]))
        q.append(now)
        return None


def reset() -> None:
    with _lock:
        _hits.clear()


def rate_limited(bucket: str, per_minute: int | None = None) -> Callable[[Request], None]:
    """FastAPI dependency: ``Depends(rate_limited("copilot"))``."""

    def dependency(request: Request) -> None:
        limit = per_minute if per_minute is not None else get_settings().rate_limit_llm_per_minute
        wait = check(f"{bucket}:{_caller_key(request)}", limit)
        if wait is not None:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Too many AI requests — try again in {int(wait) + 1}s.",
                headers={"Retry-After": str(int(wait) + 1)},
            )

    return dependency
