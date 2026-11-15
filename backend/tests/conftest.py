"""Shared test fixtures.

Hermetic by default: LLM disabled/falling back, live providers blocked.
DB-dependent integration tests require a reachable Postgres with schema/migrations
configured via DATABASE_URL (or TEST_DATABASE_URL).
"""

import os

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


@pytest.fixture(scope="session", autouse=True)
def _test_db_url():
    """Default to local docker-compose DB for integration tests when unset."""
    if not os.environ.get("DATABASE_URL"):
        os.environ["DATABASE_URL"] = "postgresql+psycopg://jobrec:change_me_in_production@localhost:55432/jobrec"
    if not os.environ.get("TEST_DATABASE_URL"):
        os.environ["TEST_DATABASE_URL"] = os.environ["DATABASE_URL"]
    yield
