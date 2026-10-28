"""Shared test fixtures.

Three guarantees for a deterministic, hermetic suite:

1. ``LLM_STRICT`` (loaded from .env for the runtime trial) is forced off —
   the suite validates the *graceful-fallback* contract (parse_query
   degrades to FTS, polish returns the template, ...).
2. No test ever spends live provider quota or depends on the network:
   ``get_provider``/``llm_available`` are stubbed to report "no provider".
   Tests that need a provider inject their own fake, which overrides this.
3. The query-time Adzuna search is blocked the same way — ``fetch_adzuna_search``
   raises, and ``search_postings`` converts that into the platform-only
   degradation path (identical to "no keys configured").  Tests that
   exercise the live leg monkeypatch the fetch with their own fake, which
   overrides this fixture's stub for that test.
"""

import pytest

import app.services.live_jobs as live_jobs_pkg
import app.services.llm as llm_pkg
import app.services.llm.provider as provider_mod
from app.core.config import get_settings


@pytest.fixture(autouse=True)
def _llm_test_mode():
    settings = get_settings()
    previous_strict = settings.llm_strict
    settings.llm_strict = False
    previous_get = provider_mod.get_provider
    previous_avail = provider_mod.llm_available
    provider_mod.get_provider = lambda: None
    provider_mod.llm_available = lambda: False
    llm_pkg.get_provider = provider_mod.get_provider
    llm_pkg.llm_available = provider_mod.llm_available
    yield
    provider_mod.get_provider = previous_get
    provider_mod.llm_available = previous_avail
    llm_pkg.get_provider = previous_get
    llm_pkg.llm_available = previous_avail
    settings.llm_strict = previous_strict


@pytest.fixture(autouse=True)
def _no_live_provider(monkeypatch):
    """Never hit api.adzuna.com from the suite (quota + determinism)."""

    def _blocked(*_args, **_kwargs):
        raise RuntimeError("live Adzuna provider is blocked in tests")

    monkeypatch.setattr(live_jobs_pkg, "fetch_adzuna_search", _blocked)
