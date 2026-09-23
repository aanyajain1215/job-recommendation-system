"""Tests for the Applications API.

Covers:
- POST  /api/v1/jobs/{job_id}/apply (successful atomic apply + interaction log)
- POST  /api/v1/jobs/{job_id}/apply (duplicate conflict 409)
- POST  /api/v1/jobs/{job_id}/apply (nonexistent job 404)
- POST  /api/v1/jobs/{job_id}/apply (role protection 403)
- GET   /api/v1/applications/me (paginated candidate applications)
- GET   /api/v1/applications/me/stats (lightweight status aggregation)
- GET   /api/v1/employer/jobs/{job_id}/applications (ownership verification 403 & success 200)
- PATCH /api/v1/employer/applications/{id}/status (status update)
"""

from uuid import UUID, uuid4
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.db import SessionLocal
from app.main import app
from app.models.enums import InteractionType
from app.models.interaction import Interaction
from app.models.job import Job
from app.models.user import User

client = TestClient(app, raise_server_exceptions=False)


def _delete_job(job_id) -> None:
    """Fixture teardown: remove a created job (cascades to skills/applications/interactions)."""
    with SessionLocal() as db:
        row = db.get(Job, UUID(str(job_id)))
        if row is not None:
            db.delete(row)
            db.commit()


def _delete_user(user_id) -> None:
    """Fixture teardown: remove a registered test account."""
    with SessionLocal() as db:
        row = db.get(User, UUID(str(user_id)))
        if row is not None:
            db.delete(row)
            db.commit()


@pytest.fixture
def seeker_user():
    uid = uuid4().hex[:8]
    reg = client.post(
        "/api/v1/auth/register",
        json={
            "email": f"seeker_{uid}@example.com",
            "password": "Password123!",
            "role": "job_seeker",
        },
    )
    assert reg.status_code == 201, reg.text
    token = reg.json()["access_token"]
    user_id = reg.json()["user"]["id"]
    yield {
        "headers": {"Authorization": f"Bearer {token}"},
        "token": token,
        "id": user_id,
        "email": f"seeker_{uid}@example.com",
    }
    _delete_user(user_id)


@pytest.fixture
def employer_user():
    uid = uuid4().hex[:8]
    reg = client.post(
        "/api/v1/auth/register",
        json={
            "email": f"employer_{uid}@example.com",
            "password": "Password123!",
            "role": "employer",
        },
    )
    assert reg.status_code == 201, reg.text
    token = reg.json()["access_token"]
    user_id = reg.json()["user"]["id"]
    yield {
        "headers": {"Authorization": f"Bearer {token}"},
        "token": token,
        "id": user_id,
        "email": f"employer_{uid}@example.com",
    }
    _delete_user(user_id)


@pytest.fixture
def another_employer():
    uid = uuid4().hex[:8]
    reg = client.post(
        "/api/v1/auth/register",
        json={
            "email": f"other_emp_{uid}@example.com",
            "password": "Password123!",
            "role": "employer",
        },
    )
    assert reg.status_code == 201, reg.text
    token = reg.json()["access_token"]
    user_id = reg.json()["user"]["id"]
    yield {
        "headers": {"Authorization": f"Bearer {token}"},
        "token": token,
    }
    _delete_user(user_id)


@pytest.fixture
def sample_job(employer_user):
    job_resp = client.post(
        "/api/v1/jobs",
        headers=employer_user["headers"],
        json={
            "title": f"Staff Software Engineer {uuid4().hex[:4]}",
            "description": "Develop high-scale distributed backend systems.",
            "requirements": "Proficiency in Python and PostgreSQL.",
            "employment_type": "full_time",
            "experience_level": "senior",
            "location": "San Francisco, CA",
            "is_remote": True,
            "salary_min": 170000,
            "salary_max": 220000,
        },
    )
    assert job_resp.status_code == 201, job_resp.text
    job = job_resp.json()
    yield job
    # Torn down before its owner (employer_user) — leftover fixture jobs
    # would otherwise pollute the shared dev corpus and recommender tests.
    _delete_job(job["id"])


class TestApplicationsAPI:

    def test_apply_to_job_success_and_transactional_interaction(self, seeker_user, sample_job):
        """Job seeker applies to an open job; application record and apply interaction are committed together."""
        resp = client.post(
            f"/api/v1/jobs/{sample_job['id']}/apply",
            headers=seeker_user["headers"],
            json={"cover_note": "Excited about this distributed systems position!"},
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()

        assert data["job_id"] == sample_job["id"]
        assert data["status"] == "applied"
        assert data["cover_note"] == "Excited about this distributed systems position!"
        assert data["job"]["id"] == sample_job["id"]
        assert "applied_at" in data

        # Verify atomic interaction record exists in the DB
        with SessionLocal() as db:
            interaction = db.scalar(
                select(Interaction).where(
                    Interaction.job_id == sample_job["id"],
                    Interaction.user_id == seeker_user["id"],
                    Interaction.event_type == InteractionType.APPLY,
                )
            )
            assert interaction is not None, "Atomic interaction log was not committed with application"

    def test_apply_to_job_duplicate_conflict_409(self, seeker_user, sample_job):
        """Applying a second time to the same job must return 409 Conflict."""
        # First apply
        r1 = client.post(
            f"/api/v1/jobs/{sample_job['id']}/apply",
            headers=seeker_user["headers"],
            json={},
        )
        assert r1.status_code == 201

        # Second apply (duplicate)
        r2 = client.post(
            f"/api/v1/jobs/{sample_job['id']}/apply",
            headers=seeker_user["headers"],
            json={"cover_note": "Trying again"},
        )
        assert r2.status_code == 409
        assert "Already applied" in r2.json()["detail"]

    def test_apply_to_nonexistent_job_404(self, seeker_user):
        """Applying to an unknown job ID returns 404."""
        resp = client.post(
            f"/api/v1/jobs/{uuid4()}/apply",
            headers=seeker_user["headers"],
            json={},
        )
        assert resp.status_code == 404

    def test_apply_role_restriction_employer_forbidden_403(self, employer_user, sample_job):
        """Employers cannot apply to jobs."""
        resp = client.post(
            f"/api/v1/jobs/{sample_job['id']}/apply",
            headers=employer_user["headers"],
            json={},
        )
        assert resp.status_code == 403

    def test_get_my_applications(self, seeker_user, sample_job):
        """Seeker lists their submitted applications with embedded job details."""
        client.post(
            f"/api/v1/jobs/{sample_job['id']}/apply",
            headers=seeker_user["headers"],
            json={"cover_note": "First application"},
        )

        resp = client.get("/api/v1/applications/me", headers=seeker_user["headers"])
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) >= 1
        assert items[0]["job"]["id"] == sample_job["id"]
        assert items[0]["status"] == "applied"

    def test_get_my_application_stats(self, seeker_user, sample_job):
        """Seeker gets aggregate pipeline statistics."""
        client.post(
            f"/api/v1/jobs/{sample_job['id']}/apply",
            headers=seeker_user["headers"],
            json={},
        )

        resp = client.get("/api/v1/applications/me/stats", headers=seeker_user["headers"])
        assert resp.status_code == 200
        stats = resp.json()
        assert stats["total_applied"] >= 1
        assert stats["applied"] >= 1
        assert "shortlisted" in stats
        assert "offer" in stats

    def test_employer_view_applicants_ownership_check(
        self, seeker_user, employer_user, another_employer, sample_job
    ):
        """The owning employer can see applicants; another employer gets 403 Forbidden."""
        # Seeker applies
        apply_resp = client.post(
            f"/api/v1/jobs/{sample_job['id']}/apply",
            headers=seeker_user["headers"],
            json={"cover_note": "Great fit for this role"},
        )
        assert apply_resp.status_code == 201

        # Another employer attempts to view applicants for this job -> 403 Forbidden
        other_resp = client.get(
            f"/api/v1/employer/jobs/{sample_job['id']}/applications",
            headers=another_employer["headers"],
        )
        assert other_resp.status_code == 403, "Horizonal authorization breach: other employer saw applicants"

        # Owning employer views applicants -> 200 OK
        owner_resp = client.get(
            f"/api/v1/employer/jobs/{sample_job['id']}/applications",
            headers=employer_user["headers"],
        )
        assert owner_resp.status_code == 200
        applicants = owner_resp.json()
        assert len(applicants) == 1
        assert applicants[0]["job_id"] == sample_job["id"]
        assert applicants[0]["user_id"] == seeker_user["id"]
        assert applicants[0]["cover_note"] == "Great fit for this role"

    def test_employer_update_application_status(
        self, seeker_user, employer_user, sample_job
    ):
        """Owning employer transitions an applicant from 'applied' to 'shortlisted'."""
        apply_resp = client.post(
            f"/api/v1/jobs/{sample_job['id']}/apply",
            headers=seeker_user["headers"],
            json={},
        )
        app_id = apply_resp.json()["id"]

        patch_resp = client.patch(
            f"/api/v1/employer/applications/{app_id}/status",
            headers=employer_user["headers"],
            json={"status": "shortlisted"},
        )
        assert patch_resp.status_code == 200
        assert patch_resp.json()["status"] == "shortlisted"

        # Verify seeker's stats endpoint reflects the updated status
        stats_resp = client.get("/api/v1/applications/me/stats", headers=seeker_user["headers"])
        assert stats_resp.status_code == 200
        assert stats_resp.json()["shortlisted"] >= 1
