"""Query-time live search (transient Adzuna results, never persisted).

Covers the live-data conversion: keyword searches hit the provider at request
time (no ingested corpus), live items arrive as transient externals
(``adzuna-…`` ids, ``source: "adzuna"``, no DB FKs), filter-only views stay on
platform rows, and the live leg never writes to the database.  The provider is
monkeypatched per test — the shared conftest blocks the real one (quota and
network are never touched by the suite).
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.db import SessionLocal
from app.main import app
from app.models.enums import EmploymentType, ExperienceLevel
from app.models.job import Job
from app.models.ops import SystemConfig
from app.models.user import User
from app.services import live_jobs

client = TestClient(app, raise_server_exceptions=False)


def _raw_row(external_id: str, title: str) -> dict:
    """One fake provider row (the shape fetch_adzuna_search returns)."""
    return {
        "source": "adzuna",
        "external_id": external_id,
        "title": title,
        "description": f"{title} building reliable systems with Python and React in production.",
        "company": "LiveCo",
        "location": "Remote",
        "salary_min": None,
        "salary_max": None,
        "currency": None,
        "url": f"https://www.adzuna.in/details/{external_id}",
        "posted_at": "2026-10-01T00:00:00Z",
        "is_remote": True,
    }


@pytest.fixture(autouse=True)
def _live_cache_clean():
    """The 120s TTL cache would leak state between tests."""
    live_jobs._search_cache.clear()
    yield
    live_jobs._search_cache.clear()


@pytest.fixture
def fake_adzuna(monkeypatch):
    """Deterministic provider stub → (rows, count); records the queries asked."""
    calls: list[str] = []

    def _fetch(
        query,
        page=1,
        *,
        results_per_page=25,
        where=None,
        sort_by=None,
        full_time=None,
        timeout=None,
    ):
        calls.append(query)
        return [
            _raw_row("111222333", "Quantum Widget Engineer"),
            _raw_row("444555666", "Quantum Widget Architect"),
        ], 123

    monkeypatch.setattr(live_jobs, "fetch_adzuna_search", _fetch)
    return calls


def test_keyword_search_merges_live_items(fake_adzuna):
    resp = client.get("/api/v1/jobs", params={"q": "engineer", "page_size": 20})
    assert resp.status_code == 200, resp.text
    data = resp.json()

    live = [j for j in data["items"] if j["id"].startswith("adzuna-")]
    assert live, "keyword search must fetch live Adzuna results at query time"
    assert fake_adzuna and fake_adzuna[0] == "engineer"

    # Transient contract: own source, no DB FKs, provider link.
    item = live[0]
    assert item["source"] == "adzuna"
    assert item["company_id"] is None
    assert item["posted_by_user_id"] is None
    assert (item["external_url"] or "").startswith("https://www.adzuna.in/details/")

    # Platform rows come first; live results fill the rest of the window.
    flags = [j["id"].startswith("adzuna-") for j in data["items"]]
    assert flags == sorted(flags), "platform matches must precede live results"
    # total = platform matches + Adzuna's own count.
    assert data["total"] >= 123


def test_filter_only_view_stays_platform(fake_adzuna):
    resp = client.get("/api/v1/jobs", params={"is_remote": "true", "page_size": 10})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert all(not j["id"].startswith("adzuna-") for j in data["items"])
    assert all(j["source"] == "native" for j in data["items"])
    assert fake_adzuna == [], "provider must not run for filter-only views"


def test_live_search_persists_nothing(fake_adzuna):
    with SessionLocal() as db:
        before = db.scalar(select(func.count()).select_from(Job))

    resp = client.get("/api/v1/jobs", params={"q": "quantum widget"})
    assert resp.status_code == 200, resp.text
    assert any(j["id"].startswith("adzuna-") for j in resp.json()["items"])

    with SessionLocal() as db:
        after = db.scalar(select(func.count()).select_from(Job))
    assert after == before, "live results must never materialize into jobs"


def test_live_detail_404s_with_provider_message():
    resp = client.get(f"/api/v1/jobs/{live_jobs.live_id('111222333')}")
    assert resp.status_code == 404
    assert "Live listings open on the provider's site." in resp.json()["detail"]


def test_unknown_native_job_still_404s():
    resp = client.get(f"/api/v1/jobs/{uuid4()}")
    assert resp.status_code == 404


def test_long_query_retries_once_with_first_three_words(monkeypatch):
    """Adzuna ANDs `what` terms — recall rescue, still this query's results."""
    seen: list[str] = []

    def _fetch(query, page=1, **kwargs):
        seen.append(query)
        if len(query.split()) > 3:
            return [], 0  # AND-semantics miss
        return [_raw_row("555666777", "Senior Widget Engineer")], 7

    monkeypatch.setattr(live_jobs, "fetch_adzuna_search", _fetch)
    postings, total = live_jobs.search_postings("senior widget engineer role")

    assert seen == ["senior widget engineer role", "senior widget engineer"]
    assert total == 7
    assert [p["external_id"] for p in postings] == ["555666777"]


# --- recommendation feed ----------------------------------------------------


def _register_seeker() -> dict:
    token = uuid4().hex[:8]
    reg = client.post(
        "/api/v1/auth/register",
        json={
            "email": f"livefeed_{token}@example.com",
            "password": "Password123!",
            "role": "job_seeker",
        },
    )
    assert reg.status_code == 201, reg.text
    body = reg.json()
    return {
        "headers": {"Authorization": f"Bearer {body['access_token']}"},
        "id": body["user"]["id"],
    }


def _delete_user(user_id) -> None:
    from uuid import UUID

    uid = UUID(str(user_id))
    with SessionLocal() as db:
        row = db.get(SystemConfig, f"m4:{uid}")
        if row is not None:
            db.delete(row)
        user = db.get(User, uid)
        if user is not None:
            db.delete(user)
        db.commit()


def test_feed_serves_live_candidates(monkeypatch):
    """Feed merges transient live candidates — and snapshots only DB rows.

    Regression guard: a live item once crashed the feed (transient company
    poisoned CompanySummary) and would also break snapshot persistence
    (``UUID("adzuna-…")``); the endpoint must serve both kinds at 200.
    """
    account = _register_seeker()
    try:
        put = client.put(
            "/api/v1/profiles/me",
            headers=account["headers"],
            json={"headline": "Backend engineer", "bio": "Python and FastAPI developer"},
        )
        assert put.status_code in (200, 201), put.text

        posting = {
            "external_id": "999888777",
            "title": "Live Feed Role",
            "description": "A live role serving Python services and React frontends every day.",
            "company": "FeedCo",
            "location": "Remote",
            "is_remote": True,
            "salary_min": None,
            "salary_max": None,
            "currency": "USD",
            "url": "https://www.adzuna.in/details/999888777",
            "created_at": datetime.now(timezone.utc),
            "employment_type": EmploymentType.FULL_TIME,
            "experience_level": ExperienceLevel.MID,
            "skills": [("python", True)],
            "family": None,
        }

        def _fake_live(db, profile, limit):
            with SessionLocal() as session:
                return [live_jobs.transient_job(session, posting)]

        monkeypatch.setattr(live_jobs, "live_candidates", _fake_live)

        feed = client.get(
            "/api/v1/recommendations",
            params={"limit": 10},
            headers=account["headers"],
        )
        assert feed.status_code == 200, feed.text

        items = feed.json()["items"]
        live = [i for i in items if i["job"]["id"].startswith("adzuna-")]
        assert live, "feed must include live candidates"
        assert live[0]["job"]["source"] == "adzuna"
        assert live[0]["job"]["company_id"] is None
        # Platform items (any) coexist in the same scored feed.
        assert any(not i["job"]["id"].startswith("adzuna-") for i in items)
    finally:
        _delete_user(account["id"])
