"""§14 project relevance mapping: exact band thresholds, ×1.6 required rule,
both §13 directions (job card + profile benefits), threshold enforcement.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.db import SessionLocal
from app.main import app
from app.models.job import Job
from app.models.user import User
from app.services.project_mapping import (
    band_for,
    family_benefits,
    powered_by_label,
    rank_projects,
    score_project,
)
from app.services.scoring import JobSkillReq

client = TestClient(app, raise_server_exceptions=False)

BANDS = {"Very high", "High", "Moderate", "Low"}


def _delete_user(user_id) -> None:
    from uuid import UUID

    with SessionLocal() as db:
        row = db.get(User, UUID(str(user_id)))
        if row is not None:
            db.delete(row)
            db.commit()


@pytest.fixture
def seeker():
    token = uuid4().hex[:8]
    reg = client.post(
        "/api/v1/auth/register",
        json={
            "email": f"pm_{token}@example.com",
            "password": "Password123!",
            "role": "job_seeker",
        },
    )
    assert reg.status_code == 201, reg.text
    body = reg.json()
    account = {
        "headers": {"Authorization": f"Bearer {body['access_token']}"},
        "id": body["user"]["id"],
    }
    yield account
    _delete_user(account["id"])


@pytest.fixture
def corpus_job():
    with SessionLocal() as db:
        job = db.scalar(
            select(Job).join(Job.skills).order_by(Job.created_at, Job.id).limit(1)
        )
        assert job is not None
        yield {"id": str(job.id), "title": job.title}


class _Project:
    def __init__(self, pid, title, skills):
        self.id = pid
        self.title = title
        self.detected_skills = skills


class _Family:
    def __init__(self, name, core):
        self.name = name
        self.core_skills = core


class TestBands:

    def test_exact_thresholds(self):
        assert band_for(70.0) == "Very high"
        assert band_for(69.9) == "High"
        assert band_for(50.0) == "High"
        assert band_for(49.9) == "Moderate"
        assert band_for(35.0) == "Moderate"
        assert band_for(34.9) == "Low"
        assert band_for(0.0) == "Low"
        assert band_for(100.0) == "Very high"

    def test_required_weighting_1_6(self):
        job_skills = [
            JobSkillReq(name="python", is_required=True, importance_weight=1.0),
            JobSkillReq(name="django", is_required=False, importance_weight=1.0),
        ]
        score, matched = score_project({"python"}, job_skills)
        # 1.6 / (1.6 + 1.0) = 61.538… → 61.5
        assert score == pytest.approx(61.5, abs=0.1)
        assert matched == ["python"]
        assert band_for(score) == "High"

    def test_empty_inputs_score_zero(self):
        assert score_project(set(), [JobSkillReq(name="python")]) == (0.0, [])
        assert score_project({"python"}, []) == (0.0, [])

    def test_full_overlap_is_100(self):
        job_skills = [JobSkillReq(name="python", is_required=True)]
        score, _ = score_project({"python"}, job_skills)
        assert score == 100.0


class TestSurfacing:

    def test_rank_orders_best_first(self):
        projects = [
            _Project(uuid4(), "Weak", {"react"}),
            _Project(uuid4(), "Strong", {"python", "fastapi", "sql"}),
        ]
        job_skills = [
            JobSkillReq(name="python", is_required=True),
            JobSkillReq(name="fastapi", is_required=True),
            JobSkillReq(name="sql", is_required=True),
        ]
        ranked = rank_projects(projects, job_skills)
        assert ranked[0].title == "Strong"
        assert ranked[0].band == "Very high"

    def test_low_band_never_surfaced(self):
        """Threshold enforcement: no 'Powered by' for a Low band (§14)."""
        projects = [_Project(uuid4(), "Frontend only", {"react"})]
        job_skills = [JobSkillReq(name="python", is_required=True)]
        assert powered_by_label(projects, job_skills) is None
        assert powered_by_label([], job_skills) is None

        ok_projects = [_Project(uuid4(), "Backend API", {"python"})]
        label = powered_by_label(ok_projects, job_skills)
        assert label is not None
        assert label.startswith("Backend API — ")

    def test_family_benefits_bands(self):
        projects = [_Project(uuid4(), "Data pipeline", {"python", "sql"})]
        families = [
            _Family("Data Analytics", ["python", "sql", "tableau"]),
            _Family("DevOps", ["kubernetes", "terraform"]),
        ]
        rows = family_benefits(projects, families)
        assert len(rows) == 1
        benefits = {b["family"]: b for b in rows[0]["benefits"]}
        # overlap 2 of 3 core skills (×1.6 each, uniform) → 66.7 → "High"
        assert "Data Analytics" in benefits
        assert benefits["Data Analytics"]["band"] == "High"
        assert benefits["Data Analytics"]["score"] == pytest.approx(66.7, abs=0.1)
        # zero-overlap family contributes no benefit row
        assert "DevOps" not in benefits

    def test_family_benefits_excludes_zero_overlap(self):
        projects = [_Project(uuid4(), "P", {"react"})]
        families = [_Family("DevOps", ["kubernetes"])]
        rows = family_benefits(projects, families)
        assert rows[0]["benefits"] == []


class TestProjectMapApi:

    def test_job_project_map_shape(self, seeker, corpus_job):
        resp = client.get(
            f"/api/v1/jobs/{corpus_job['id']}/project-map",
            headers=seeker["headers"],
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["job_id"] == corpus_job["id"]
        assert isinstance(data["items"], list)
        # fresh profile: no projects → empty map, nothing surfaced
        assert data["best"] is None
        assert data["powered_by"] is None

    def test_project_map_requires_auth(self, corpus_job):
        resp = client.get(f"/api/v1/jobs/{corpus_job['id']}/project-map")
        assert resp.status_code in (401, 403)

    def test_profile_project_benefits_shape(self, seeker):
        resp = client.get(
            "/api/v1/profiles/me/project-benefits",
            headers=seeker["headers"],
        )
        # fresh profile has no project rows — endpoint still responds 404-free
        # only if a profile exists; register flow doesn't auto-create one.
        assert resp.status_code in (200, 404)
        if resp.status_code == 200:
            assert isinstance(resp.json()["items"], list)

    def test_unknown_job_404(self, seeker):
        resp = client.get(
            f"/api/v1/jobs/{uuid4()}/project-map",
            headers=seeker["headers"],
        )
        assert resp.status_code == 404


class TestFeedSurfaces:

    def test_recommendation_job_has_project_relevance_field(self, seeker):
        """Feed items expose job.project_relevance (§18 additive field)."""
        resp = client.get(
            "/api/v1/recommendations",
            params={"limit": 3},
            headers=seeker["headers"],
        )
        assert resp.status_code == 200, resp.text
        items = resp.json()["items"]
        if items:
            value = items[0]["job"]["project_relevance"]
            assert value is None or isinstance(value, str)
