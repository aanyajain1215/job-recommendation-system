import json
import time
from collections import defaultdict, deque
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from app.api import api_router
from app.core.config import get_settings
from app.services.llm import LlmStrictError


_RATE_BUCKETS: dict[str, deque[float]] = defaultdict(deque)
_IDEMPOTENCY_STORE: dict[str, tuple[float, int, dict[str, str], bytes]] = {}
_IDEMPOTENCY_TTL = 300.0


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title="JobRec API",
        description="Job recommendation platform API",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @application.middleware("http")
    async def rate_limit_middleware(request: Request, call_next):
        # simple in-memory rate limit (best-effort, per-process; prod can front with nginx/gateway)
        limit = int(getattr(settings, "rate_limit_per_minute", 120) or 120)
        if limit > 0 and request.url.path.startswith("/api/"):
            ident = request.headers.get("x-forwarded-for") or (request.client.host if request.client else "unknown")
            key = f"{ident}:{request.url.path.split('/')[3] if len(request.url.path.split('/'))>3 else 'root'}"
            now = time.time()
            bucket = _RATE_BUCKETS[key]
            while bucket and now - bucket[0] > 60:
                bucket.popleft()
            if len(bucket) >= limit:
                return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded. Please retry shortly."}, headers={"Retry-After": "60"})
            bucket.append(now)
        return await call_next(request)

    @application.middleware("http")
    async def idempotency_middleware(request: Request, call_next):
        # Idempotency-Key support for mutating requests (in-memory TTL; prevents duplicate side effects on retries)
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            idem = request.headers.get("Idempotency-Key")
            if idem:
                user = request.headers.get("Authorization", "anon")[:32]
                key = f"{user}:{request.method}:{request.url.path}:{idem}"
                now = time.time()
                # cleanup occasionally
                if len(_IDEMPOTENCY_STORE) > 5000:
                    for k, v in list(_IDEMPOTENCY_STORE.items()):
                        if now - v[0] > _IDEMPOTENCY_TTL:
                            _IDEMPOTENCY_STORE.pop(k, None)
                cached = _IDEMPOTENCY_STORE.get(key)
                if cached and now - cached[0] <= _IDEMPOTENCY_TTL:
                    status_code, headers, body = cached[1], cached[2], cached[3]
                    return Response(content=body, status_code=status_code, headers={**headers, "Idempotent-Replayed": "true"}, media_type=headers.get("content-type", "application/json"))
                response = await call_next(request)
                try:
                    body = b""
                    async for chunk in response.body_iterator:  # type: ignore[attr-defined]
                        body += chunk
                    headers = {k: v for k, v in response.headers.items() if k.lower() in {"content-type"}}
                    _IDEMPOTENCY_STORE[key] = (now, response.status_code, headers, body)
                    return Response(content=body, status_code=response.status_code, headers=dict(response.headers), media_type=response.media_type)
                except Exception:
                    return response
        return await call_next(request)

    application.include_router(api_router, prefix="/api/v1")

    @application.exception_handler(LlmStrictError)
    async def _llm_strict_error(request: Request, exc: LlmStrictError) -> JSONResponse:
        # LLM_STRICT=true trial mode: surface AI failures as a clear 502
        # instead of the routes' silent deterministic fallbacks.
        return JSONResponse(status_code=502, content={"detail": f"AI failure: {exc}"})

    return application


app = create_app()
