"""LLM_STRICT trial-mode contract: bail loudly under strict, degrade quietly
otherwise — and never depend on a live provider (see conftest)."""

from __future__ import annotations

import pytest

from app.core.config import get_settings
from app.services.llm.strict import LlmStrictError, strict_bail
from app.services import nl_search


class TestStrictBail:

    def test_raises_when_strict_enabled(self, monkeypatch):
        monkeypatch.setattr(get_settings(), "llm_strict", True)
        with pytest.raises(LlmStrictError, match="test_route: boom"):
            strict_bail("test_route", "boom")

    def test_noop_when_strict_disabled(self, monkeypatch):
        monkeypatch.setattr(get_settings(), "llm_strict", False)
        strict_bail("test_route", "boom")  # must not raise

    def test_parse_query_bails_without_provider_under_strict(self, monkeypatch):
        # conftest already stubs get_provider -> None
        monkeypatch.setattr(get_settings(), "llm_strict", True)
        with pytest.raises(LlmStrictError, match="nl_search"):
            nl_search.parse_query("remote python jobs in berlin")

    def test_parse_query_degrades_without_provider_when_not_strict(self, monkeypatch):
        monkeypatch.setattr(get_settings(), "llm_strict", False)
        filters, mode = nl_search.parse_query("remote python jobs in berlin")
        assert mode == "fts"
        assert filters.keywords
