"""Per-card skill-gap previews on job search / AI search (plan §8/§17).

Search cards must highlight disparities for every result — platform rows and
transient live (Adzuna) rows alike — using the same matched/missing contract
as the recommendation feed.  These tests pin:

- annotated only for signed-in seekers that actually list skills,
- live results (no DB row, no /gap/{id} page) get the same chips,
- NL search gets them too,
- anonymous requests are unchanged (additive fields stay empty/None).
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.db import SessionLocal
from app.main import app
from app.models.job import Job
from app.models.user import User
from app.services import live_jobs

client = TestClient(app, raise_server_exceptions=False)


def _register(role: str, company_name: str | None = None) -> dict:
    payload = {
        "email": f"gap_{role}_{uuid4().hex[:8]}@example.com",
        "password": "Password123!",
        "role": role,
    }
    if company_name:
        payload["company_name"] = company_name
    reg = client.post("/api/v1/auth/register", json=payload)
    assert reg.status_code == 201, reg.text
    body = reg.json()
    return {
        "headers": {"Authorization": f"Bearer {body['access_token']}"},
        "id": body["user"]["id"],
    }


def _delete_user(user_id) -> None:
    with SessionLocal() as db:
        row = db.get(User, UUID(str(user_id)))
        if row is not None:
            db.delete(row)
            db.commit()


def _delete_job(job_id) -> None:
    with SessionLocal() as db:
        row = db.get(Job, UUID(str(job_id)))
        if row is not None:
            db.delete(row)
            db.commit()


PYTHON = "Python"
KUBERNETES = "Kubernetes"


@pytest.fixture
def seeker_with_python():
    seeker = _register("job_seeker")
    put = client.put(
        "/api/v1/profiles/me",
        headers=seeker["headers"],
        json={
            "headline": "Backend engineer",
            "skills": [
                {"skill_name": PYTHON, "proficiency_level": "advanced"},
            ],
        },
    )
    assert put.status_code in (200, 201), put.text
    yield seeker
    _delete_user(seeker["id"])


@pytest.fixture
def native_job():
    """Employer posts a job requiring Python (held) + Kubernetes (missing)."""
    employer = _register("employer", company_name=f"GapCo {uuid4().hex[:6]}")
    created = client.post(
        "/api/v1/jobs",
        headers=employer["headers"],
        json={
            "title": f"Gap Preview Engineer {uuid4().hex[:6]}",
            "description": "Build services with Python on Kubernetes.",
            "location": "Remote",
            "is_remote": True,
            "skills": [
                {"skill_name": PYTHON, "is_required": True},
                {"skill_name": KUBERNETES, "is_required": True},
            ],
        },
    )
    assert created.status_code == 201, created.text
    job = created.json()
    yield job
    _delete_job(job["id"])
    _delete_user(employer["id"])


@pytest.fixture
def fake_adzuna(monkeypatch):
    """Provider stub with skills the seeker partially holds."""

    def _fetch(query, page=1, **kwargs):
        raw = {
            "source": "adzuna",
            "external_id": "gap900100",
            "title": "Platform Engineer",
            "description": "Python services and React frontends deployed on AWS.",
            "company": "LiveGapCo",
            "location": "Remote",
            "salary_min": None,
            "salary_max": None,
            "currency": None,
            "url": "https://www.adzuna.in/details/gap900100",
            "posted_at": "2026-10-01T00:00:00Z",
            "is_remote": True,
        }
        return [raw], 1

    monkeypatch.setattr(live_jobs, "fetch_adzuna_search", _fetch)
    live_jobs._search_cache.clear()
    yield
    live_jobs._search_cache.clear()


def _find(items: list[dict], needle: str) -> dict:
    for item in items:
        if needle.lower() in item["title"].lower():
            return item
    raise AssertionError(f"no item matching {needle!r}: {[i['title'] for i in items]}")


def _assert_python_preview(item: dict) -> None:
    matched = [s.lower() for s in item["matched_skills"]]
    assert PYTHON.lower() in matched, f"expected Python in matched: {item['matched_skills']}"
    assert item["skill_match_score"] is not None
    assert 0.0 <= item["skill_match_score"] <= 100.0
    assert any(KUBERNETES.lower() == s.lower() for s in item["missing_skills"]) or any(
        "kubernetes" == s.lower() for s in item["missing_skills"]
    )


# --- platform cards ---------------------------------------------------------


def test_platform_search_card_gets_gap_preview(seeker_with_python, native_job):
    resp = client.get(
        "/api/v1/jobs",
        params={"q": native_job["title"], "page_size": 20},
        headers=seeker_with_python["headers"],
    )
    assert resp.status_code == 200, resp.text
    item = _find(resp.json()["items"], native_job["title"])
    _assert_python_preview(item)


def test_anonymous_search_has_no_gap_preview(native_job):
    resp = client.get(
        "/api/v1/jobs",
        params={"q": native_job["title"], "page_size": 20},
    )
    assert resp.status_code == 200, resp.text
    item = _find(resp.json()["items"], native_job["title"])
    assert item["matched_skills"] == []
    assert item["missing_skills"] == []
    assert item["transferable_skills"] == []
    assert item["skill_match_score"] is None


def test_profile_without_skills_has_no_gap_preview(native_job):
    bare = _register("job_seeker")
    try:
        client.put(
            "/api/v1/profiles/me",
            headers=bare["headers"],
            json={"headline": "Explorer"},
        )
        resp = client.get(
            "/api/v1/jobs",
            params={"q": native_job["title"], "page_size": 20},
            headers=bare["headers"],
        )
        assert resp.status_code == 200, resp.text
        item = _find(resp.json()["items"], native_job["title"])
        assert item["skill_match_score"] is None
        assert item["matched_skills"] == []
    finally:
        _delete_user(bare["id"])


def test_job_detail_gets_gap_preview(seeker_with_python, native_job):
    resp = client.get(
        f"/api/v1/jobs/{native_job['id']}",
        headers=seeker_with_python["headers"],
    )
    assert resp.status_code == 200, resp.text
    _assert_python_preview(resp.json())


# --- live + AI search -------------------------------------------------------


def test_live_search_results_get_gap_preview(seeker_with_python, fake_adzuna):
    # Query token that matches no platform row, so page 1 is filled by the
    # stubbed live leg (the provider stub ignores the query text).
    resp = client.get(
        "/api/v1/jobs",
        params={"q": "zzlivegap", "page_size": 20},
        headers=seeker_with_python["headers"],
    )
    assert resp.status_code == 200, resp.text
    live = [j for j in resp.json()["items"] if j["id"].startswith("adzuna-")]
    assert live, "expected the stubbed live result"
    item = live[0]
    matched = [s.lower() for s in item["matched_skills"]]
    assert PYTHON.lower() in matched
    assert item["skill_match_score"] is not None
    # No persisted row — the preview is the only gap surface for live cards.
    assert item["company_id"] is None


def test_live_search_anonymous_has_no_preview(fake_adzuna):
    resp = client.get(
        "/api/v1/jobs",
        params={"q": "zzlivegap", "page_size": 20},
    )
    assert resp.status_code == 200, resp.text
    live = [j for j in resp.json()["items"] if j["id"].startswith("adzuna-")]
    assert live
    assert live[0]["skill_match_score"] is None
    assert live[0]["missing_skills"] == []


def test_nl_search_cards_get_gap_preview(seeker_with_python, fake_adzuna):
    resp = client.get(
        "/api/v1/jobs/nl",
        params={"q": "zzlivegap"},
        headers=seeker_with_python["headers"],
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["items"], data
    live = [j for j in data["items"] if j["id"].startswith("adzuna-")]
    assert live, "NL search must merge the stubbed live leg"
    matched = [s.lower() for s in live[0]["matched_skills"]]
    assert PYTHON.lower() in matched
    assert live[0]["skill_match_score"] is not None
