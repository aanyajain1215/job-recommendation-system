"""Country-aware search: free-text extraction, Adzuna routing, country-first order.

Regression context: a query like "software engineer jobs in Germany" used to
fall back to whole-sentence FTS and surface USA/Mexico/EMEA postings above the
requested country.  The live leg was also hard-wired to ADZUNA_COUNTRY, so a
German request queried the Indian marketplace with ``where=Germany``.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app
from app.services import live_jobs, location_hint
from app.services.ingest import fetch as fetch_mod

client = TestClient(app, raise_server_exceptions=False)


def _raw_row(external_id: str, title: str, location: str, url: str | None = None) -> dict:
    return {
        "source": "adzuna",
        "external_id": external_id,
        "title": title,
        "description": f"{title} building reliable systems with Python and React in production.",
        "company": "LiveCo",
        "location": location,
        "salary_min": None,
        "salary_max": None,
        "currency": None,
        "url": url or f"https://www.adzuna.de/details/{external_id}",
        "posted_at": "2026-10-01T00:00:00Z",
        "is_remote": False,
    }


@pytest.fixture(autouse=True)
def _live_cache_clean():
    live_jobs._search_cache.clear()
    yield
    live_jobs._search_cache.clear()


# --- deterministic extraction -------------------------------------------------


@pytest.mark.parametrize(
    ("query", "label", "code", "stripped"),
    [
        ("software engineer jobs in Germany", "Germany", "de", "software engineer jobs"),
        ("find me data jobs in the USA", "United States", "us", "find me data jobs"),
        ("remote python jobs in bangalore", "Bengaluru", "in", "remote python jobs"),
        ("Berlin backend roles", "Berlin", "de", "backend roles"),
        ("senior developer in New Zealand", "New Zealand", "nz", "senior developer"),
        ("data analyst in South Africa", "South Africa", "za", "data analyst"),
        ("Software Engineer Germany", "Germany", "de", "Software Engineer"),
    ],
)
def test_detect_and_strip_location(query, label, code, stripped):
    hint = location_hint.detect_location(query)
    assert hint is not None
    assert hint.label == label
    assert hint.country_code == code
    assert location_hint.strip_location(query, hint) == stripped


def test_detect_location_returns_none_without_a_place():
    assert location_hint.detect_location("senior python backend engineer") is None


def test_location_matches_aliases_and_country_lists():
    hint = location_hint.detect_location("Germany")
    assert hint is not None
    assert location_hint.location_matches("Berlin, Germany", hint)
    assert location_hint.location_matches(
        "Croatia, Estonia, Germany, Ireland, Italy", hint
    )
    assert not location_hint.location_matches("USA", hint)
    assert not location_hint.location_matches("EMEA", hint)

    us = location_hint.detect_location("USA")
    assert us is not None
    assert location_hint.location_matches("United States", us)
    assert location_hint.location_matches("New York, NY", us)


# --- provider routing ---------------------------------------------------------


def test_fetch_adzuna_search_routes_country_and_detail_host(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "adzuna_app_id", "test-id")
    monkeypatch.setattr(settings, "adzuna_app_key", "test-key")
    monkeypatch.setattr(settings, "adzuna_country", "in")

    seen: dict = {}

    def _fake_get_json(url, params=None, timeout=20):
        seen["url"] = url
        seen["params"] = params or {}
        return {
            "count": 1,
            "results": [
                {
                    "id": "42",
                    "title": "Backend Engineer",
                    "description": "Build services.",
                    "company": {"display_name": "ACME"},
                    "location": {"display_name": "Berlin, Germany"},
                    "created": "2026-10-01T00:00:00Z",
                }
            ],
        }

    monkeypatch.setattr(fetch_mod, "_get_json", _fake_get_json)

    rows, total = fetch_mod.fetch_adzuna_search(
        "software engineer", where="Germany", country="de"
    )
    assert total == 1
    assert "/jobs/de/search/1" in seen["url"]
    assert seen["params"]["where"] == "Germany"
    assert rows[0]["url"].startswith("https://www.adzuna.de/details/")


def test_search_postings_passes_country_and_uses_local_currency(monkeypatch):
    seen: dict = {}

    def _fetch(query, page=1, **kwargs):
        seen.update(kwargs)
        seen["query"] = query
        return [_raw_row("555", "Backend Engineer", "Berlin, Germany")], 1

    monkeypatch.setattr(live_jobs, "fetch_adzuna_search", _fetch)
    postings, total = live_jobs.search_postings(
        "software engineer", location="Germany", country="de"
    )

    assert total == 1
    assert seen["country"] == "de"
    assert seen["where"] == "Germany"
    assert postings[0]["currency"] == "EUR"


# --- country-first ranking ----------------------------------------------------


def _install_country_live_stub(monkeypatch) -> list[dict]:
    calls: list[dict] = []

    def _fetch(query, page=1, **kwargs):
        calls.append({"query": query, **kwargs})
        return [
            _raw_row("de-1", "German Backend Engineer", "Berlin, Germany"),
            _raw_row("de-2", "German Platform Engineer", "Munich, Germany"),
        ], 2

    monkeypatch.setattr(live_jobs, "fetch_adzuna_search", _fetch)
    return calls


def _assert_country_first(items: list[dict], needle: str) -> None:
    flags = [needle in (item.get("location") or "").lower() for item in items]
    assert any(flags), f"expected at least one {needle!r} result: {[i['location'] for i in items]}"
    assert flags == sorted(flags, reverse=True), (
        "requested-country matches must precede other countries: "
        f"{[i['location'] for i in items]}"
    )


def test_nl_search_puts_requested_country_first(monkeypatch):
    calls = _install_country_live_stub(monkeypatch)

    resp = client.get(
        "/api/v1/jobs/nl",
        params={"q": "software engineer jobs in Germany", "page_size": 20},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["parsed_filters"]["location"] == "Germany"
    _assert_country_first(data["items"], "germany")

    # The live leg queries the German marketplace; the country-level `where`
    # is omitted (the index already scopes it — where=Germany matches nothing
    # on the German index), and the location phrase is not an AND-ed `what`.
    assert calls, "NL search must hit the live leg"
    assert calls[0]["where"] is None
    assert calls[0]["country"] == "de"
    assert "germany" not in calls[0]["query"].lower()


def test_structured_keyword_search_puts_requested_country_first(monkeypatch):
    calls = _install_country_live_stub(monkeypatch)

    resp = client.get(
        "/api/v1/jobs",
        params={"q": "software engineer in Germany", "page_size": 20},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    _assert_country_first(data["items"], "germany")
    assert calls and calls[0]["where"] is None
    assert calls[0]["country"] == "de"


def test_city_search_passes_city_as_live_where(monkeypatch):
    calls = _install_country_live_stub(monkeypatch)

    resp = client.get(
        "/api/v1/jobs",
        params={"q": "backend engineer in Berlin", "page_size": 20},
    )
    assert resp.status_code == 200, resp.text
    assert calls, "city search must hit the live leg"
    assert calls[0]["where"] == "Berlin"
    assert calls[0]["country"] == "de"


def test_explicit_location_filter_still_hard_filters(monkeypatch):
    _install_country_live_stub(monkeypatch)

    resp = client.get(
        "/api/v1/jobs",
        params={"q": "engineer", "location": "Germany", "page_size": 20},
    )
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert items
    # Structured location remains a hard filter: every platform row matches.
    for item in items:
        if not item["id"].startswith("adzuna-"):
            assert "germany" in (item["location"] or "").lower()
