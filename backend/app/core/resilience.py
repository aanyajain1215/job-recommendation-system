"""Resilience utilities: retries with exponential backoff, timeouts, circuit breaker."""

from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass
from typing import Callable, TypeVar

T = TypeVar("T")


def retry_call(
    fn: Callable[[], T],
    *,
    attempts: int = 3,
    base_delay: float = 0.3,
    max_delay: float = 4.0,
    jitter: float = 0.1,
    retry_exceptions: tuple[type[BaseException], ...] = (Exception,),
) -> T:
    last_exc: BaseException | None = None
    for i in range(max(1, attempts)):
        try:
            return fn()
        except retry_exceptions as exc:  # type: ignore[misc]
            last_exc = exc
            if i == attempts - 1:
                break
            delay = min(max_delay, base_delay * (2 ** i))
            delay += random.uniform(0, jitter)
            time.sleep(delay)
    assert last_exc is not None
    raise last_exc


@dataclass
class _BreakerState:
    failures: int = 0
    opened_at: float = 0.0
    half_open: bool = False


class CircuitBreaker:
    def __init__(self, failure_threshold: int = 5, recovery_timeout: float = 30.0) -> None:
        self.failure_threshold = max(1, failure_threshold)
        self.recovery_timeout = max(1.0, recovery_timeout)
        self._states: dict[str, _BreakerState] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.time()
        with self._lock:
            st = self._states.setdefault(key, _BreakerState())
            if st.failures < self.failure_threshold:
                return True
            # open: check recovery
            if now - st.opened_at >= self.recovery_timeout:
                st.half_open = True
                return True
            return False

    def record_success(self, key: str) -> None:
        with self._lock:
            self._states[key] = _BreakerState()

    def record_failure(self, key: str) -> None:
        now = time.time()
        with self._lock:
            st = self._states.setdefault(key, _BreakerState())
            st.failures += 1
            if st.failures >= self.failure_threshold:
                st.opened_at = now
                st.half_open = False

    def call(self, key: str, fn: Callable[[], T], *, fallback: Callable[[], T] | None = None) -> T:
        if not self.allow(key):
            if fallback is not None:
                return fallback()
            raise RuntimeError(f"circuit_open:{key}")
        try:
            result = fn()
            self.record_success(key)
            return result
        except Exception:
            self.record_failure(key)
            if fallback is not None:
                return fallback()
            raise


circuit_breaker = CircuitBreaker()
