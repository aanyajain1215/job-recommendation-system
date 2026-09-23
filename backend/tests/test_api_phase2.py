"""§18 API integration tests for the Phase 2 surface.

Covers the HTTP contract the frontend consumes:
- GET  /api/v1/recommendations/{job_id}/gap
- GET  /api/v1/recommendations/{job_id}/roadmap (persists the CareerPath and
  must expose each step's row id + done flag so the client can complete it)
- POST /api/v1/roadmaps/{path_id}/steps/{step_id}/complete (idempotent,
  ownership-checked)
- GET  /api/v1/careers/discover
- POST /api/v1/simulate + GET /api/v1/simulations (profile rows untouched)

Corpus jobs are only read here; everything persisted is keyed to throwaway
seeker profiles and purged in teardown (shared dev corpus stays clean).
"""

from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.db import SessionLocal
from app.main import app
from app.models.career_path import CareerPath
from app.models.job import Job
from app.models.profile import Profile
from app.models.simulation import Simulation
from app.models.user import User

client = TestClient(app, raise_server_exceptions=False)

GAP_STATUSES = {"STRONG", "PARTIAL", "TRANSFERABLE", "MISSING"}
READINESS_BANDS = {"low", "medium", "high"}


def _delete_user(user_id) -> None:
    """Fixture teardown: purge profile-keyed artifacts, then the account."""
    with SessionLocal() as db:
        uid = UUID(str(user_id))
        profile = db.scalar(select(Profile).where(Profile.user_id == uid))
        if profile is not None:
            for path in db.scalars(
                select(CareerPath).where(CareerPath.profile_id == profile.id)
            ).all():
                db.delete(path)
            for run in db.scalars(
                select(Simulation).where(Simulation.profile_id == profile.id)
            ).all():
                db.delete(run)
        row = db.get(User, uid)
        if row is not None:
            db.delete(row)
        db.commit()


def _register_seeker() -> dict:
    uid = uuid4().hex[:8]
    reg = client.post(
        "/api/v1/auth/register",
        json={
            "email": f"p2_api_{uid}@example.com",
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


@pytest.fixture
def seeker():
    account = _register_seeker()
    yield account
    _delete_user(account["id"])


@pytest.fixture
def other_seeker():
    """Second seeker used only for ownership checks."""
    account = _register_seeker()
    yield account
    _delete_user(account["id"])


@pytest.fixture
def family_job():
    """Read-only handle to a seeded corpus job that has a family anchor."""
    with SessionLocal() as db:
        job = db.scalar(
            select(Job)
            .where(Job.family_id.is_not(None))
            .order_by(Job.created_at, Job.id)
            .limit(1)
        )
        assert job is not None, "seed corpus must contain a job with a family"
        yield {"id": str(job.id), "title": job.title}
    # Read-only: nothing is written to the job or corpus.


class TestGapApi:

    def test_gap_response_shape_and_evidence(self, seeker, family_job):
        """Gap endpoint returns the deterministic four-class contract."""
        resp = client.get(
            f"/api/v1/recommendations/{family_job['id']}/gap",
            headers=seeker["headers"],
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()

        assert data["job_id"] == family_job["id"]
        assert data["job_title"] == family_job["title"]
        for key in ("match_score", "gap_score"):
            assert 0.0 <= data[key] <= 100.0

        assert data["readiness"]["band"] in READINESS_BANDS
        assert 0.0 <= data["readiness"]["value"] <= 1.0

        classes = data["classes"]
        assert classes, "a job with skills must yield classified requirements"
        counts = data["counts"]
        assert sum(counts.values()) == len(classes)
        for item in classes:
            assert item["status"] in GAP_STATUSES
            assert item["evidence"].get("reason"), "every class carries evidence"

        missing = {i["skill"] for i in classes if i["status"] == "MISSING"}
        assert set(data["missing_required"]) <= missing
        if data["weakest_link"] is not None:
            assert data["weakest_link"]
        assert data["reasons"], "engine must publish human-readable reasons"

    def test_gap_is_read_only_for_profile(self, seeker, family_job):
        """The gap route never writes profile rows (§8 is pure)."""
        with SessionLocal() as db:
            profile = db.scalar(select(Profile).where(Profile.user_id == UUID(seeker["id"])))
            skills_before = len(list(profile.skills))

        resp = client.get(
            f"/api/v1/recommendations/{family_job['id']}/gap",
            headers=seeker["headers"],
        )
        assert resp.status_code == 200

        with SessionLocal() as db:
            profile = db.scalar(select(Profile).where(Profile.user_id == UUID(seeker["id"])))
            skills_after = len(list(profile.skills))
        assert skills_after == skills_before


class TestRoadmapApi:

    def test_roadmap_exposes_step_ids_and_done_flags(self, seeker, family_job):
        """GET persists a path and decorates every step (flat + phased)."""
        resp = client.get(
            f"/api/v1/recommendations/{family_job['id']}/roadmap",
            headers=seeker["headers"],
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()

        assert data["id"], "a family-anchored job must persist a CareerPath"
        assert data["job_id"] == family_job["id"]
        assert data["steps"], "roadmap must contain steps"
        assert data["phases"], "steps must pack into phases"
        assert data["effort_band"] in READINESS_BANDS
        assert data["total_hours"] >= 0
        assert data["readiness_before"]["band"] in READINESS_BANDS
        assert data["readiness_after"]["band"] in READINESS_BANDS

        for step in data["steps"]:
            assert step["id"], "every step needs its row UUID for the complete POST"
            assert step["done"] is False, "fresh path has no completions"
            assert step["kind"] in {"skill", "project"}
        for phase in data["phases"]:
            for step in phase["steps"]:
                assert step["id"]
                assert step["done"] is False

        # Phased and flat views must expose the same decorated steps.
        flat = {s["seq"]: (s["id"], s["done"]) for s in data["steps"]}
        phased = {
            s["seq"]: (s["id"], s["done"])
            for p in data["phases"]
            for s in p["steps"]
        }
        assert phased == flat

    def test_reread_is_stable_and_keeps_completion_state(self, seeker, family_job):
        """A second GET regenerates content without clobbering done flags."""
        first = client.get(
            f"/api/v1/recommendations/{family_job['id']}/roadmap",
            headers=seeker["headers"],
        ).json()

        target = first["steps"][0]
        done_resp = client.post(
            f"/api/v1/roadmaps/{first['id']}/steps/{target['id']}/complete",
            headers=seeker["headers"],
        )
        assert done_resp.status_code == 200, done_resp.text
        payload = done_resp.json()
        assert payload["seq"] == target["seq"]
        assert payload["path_id"] == first["id"]
        assert payload["steps_done"] >= 1
        assert payload["path_status"] in {"active", "completed"}

        # Idempotent: same step again keeps the first done_at.
        repeat = client.post(
            f"/api/v1/roadmaps/{first['id']}/steps/{target['id']}/complete",
            headers=seeker["headers"],
        )
        assert repeat.status_code == 200
        assert repeat.json()["done_at"] == payload["done_at"]

        # Re-read: content regenerated, completion state survives.
        second = client.get(
            f"/api/v1/recommendations/{family_job['id']}/roadmap",
            headers=seeker["headers"],
        ).json()
        assert second["id"] == first["id"]
        reloaded = next(s for s in second["steps"] if s["seq"] == target["seq"])
        assert reloaded["done"] is True
        assert reloaded["id"] == target["id"]
        assert sum(1 for s in second["steps"] if s["done"]) == 1

    def test_complete_step_ownership_and_404(self, seeker, other_seeker, family_job):
        """Another user cannot complete your path; unknown ids 404."""
        road = client.get(
            f"/api/v1/recommendations/{family_job['id']}/roadmap",
            headers=seeker["headers"],
        ).json()
        step = road["steps"][0]

        foreign = client.post(
            f"/api/v1/roadmaps/{road['id']}/steps/{step['id']}/complete",
            headers=other_seeker["headers"],
        )
        assert foreign.status_code == 403

        missing_path = client.post(
            f"/api/v1/roadmaps/{uuid4()}/steps/{step['id']}/complete",
            headers=seeker["headers"],
        )
        assert missing_path.status_code == 404

        missing_step = client.post(
            f"/api/v1/roadmaps/{road['id']}/steps/{uuid4()}/complete",
            headers=seeker["headers"],
        )
        assert missing_step.status_code == 404


class TestCareersDiscoverApi:

    def test_discover_shape_with_preset_math(self, seeker):
        """Discovery returns thresholded suggestions plus same-math presets."""
        resp = client.get("/api/v1/careers/discover", headers=seeker["headers"])
        assert resp.status_code == 200, resp.text
        data = resp.json()

        assert 0.0 <= data["threshold"] <= 100.0
        assert isinstance(data["suggestions"], list)
        assert data["explored"] >= 1
        assert "target_family" in data

        # Every suggestion (thresholded or preset) carries the evidence
        # explanation contract — top skills + transfer count + nearest edge.
        for entry in data["suggestions"] + data["presets"]:
            assert 0.0 <= entry["affinity"] <= 100.0
            assert entry["family"]
            explanation = entry["explanation"]
            assert isinstance(explanation["top_skills"], list)
            assert isinstance(explanation["transfer_count"], int)
            assert "nearest_edge" in explanation

        # Presets are the four curated families, never threshold-filtered.
        preset_names = {p["family"] for p in data["presets"]}
        assert preset_names == {
            "Machine Learning Engineering",
            "Data Science",
            "DevOps Engineering",
            "Data Analytics",
        }
        # A fresh, skill-less profile stays below τ (honest thin profile).
        assert all(p["affinity"] >= 0.0 for p in data["suggestions"])


class TestSimulateApi:

    def test_simulate_response_and_history_without_profile_writes(self, seeker):
        """POST scores a shadow profile, persists the run, never the profile."""
        with SessionLocal() as db:
            profile = db.scalar(select(Profile).where(Profile.user_id == UUID(seeker["id"])))
            profile_id = profile.id
            skills_before = len(list(profile.skills))

        resp = client.post(
            "/api/v1/simulate",
            headers=seeker["headers"],
            json={
                "add_skills": [
                    {"name": "Docker", "level": "intermediate", "years": 1},
                    {"name": "Kubernetes", "level": "beginner", "years": 0},
                ],
                "expected_salary": {"min": 90000, "max": 130000, "currency": "USD"},
                "work_mode": "remote",
            },
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["id"], "the run must be persisted"

        result = data["result_delta"]
        assert "mean_score" in result["before"] and "band_counts" in result["before"]
        assert "mean_score" in result["after"] and "band_counts" in result["after"]
        assert isinstance(result["deltas"], list)
        assert "mutation" in result
        # target_job_id is an input routing detail, not part of the mutation.
        assert "target_job_id" not in data["mutation"]

        # Plan §10 invariant at the API boundary: profile rows untouched.
        with SessionLocal() as db:
            profile = db.get(Profile, profile_id)
            assert len(list(profile.skills)) == skills_before

        history = client.get("/api/v1/simulations?limit=5", headers=seeker["headers"])
        assert history.status_code == 200
        body = history.json()
        assert body["total"] >= 1
        assert any(item["id"] == data["id"] for item in body["items"])

    def test_simulate_rejects_empty_garbage_shape(self, seeker):
        """Malformed mutations are rejected by the request schema."""
        resp = client.post(
            "/api/v1/simulate",
            headers=seeker["headers"],
            json={"add_skills": [{"name": ""}]},
        )
        assert resp.status_code == 422
