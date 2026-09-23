"""
Tests for the interaction logging API.

These tests exercise the POST /api/v1/interactions endpoint
and the GET /api/v1/interactions/me endpoint end-to-end using
FastAPI's TestClient with a real database connection (same pattern
as existing tests in test_crud.py).

Run with: pytest tests/test_interactions.py -v
"""
import pytest
from uuid import uuid4


# ---------------------------------------------------------------------------
# Re-use the shared fixtures from existing test files (conftest / test_crud)
# ---------------------------------------------------------------------------
# We import the _common client/db setup helpers from test_crud if they exist,
# otherwise define minimal inline versions.

try:
    from tests.test_crud import client, auth_headers, sample_job  # type: ignore[import]
except ImportError:
    # Minimal self-contained setup
    import os
    os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/jobdb")

    from uuid import UUID

    from sqlalchemy import select

    from fastapi.testclient import TestClient
    from app.core.db import SessionLocal
    from app.main import app  # type: ignore[import]
    from app.models.job import Job
    from app.models.user import User

    client = TestClient(app, raise_server_exceptions=True)

    def _delete_account(email: str) -> None:
        """Fixture teardown: remove a registered test account and everything it owns."""
        with SessionLocal() as db:
            row = db.scalar(select(User).where(User.email == email))
            if row is not None:
                db.delete(row)
                db.commit()

    def _delete_job(job_id) -> None:
        """Fixture teardown: remove a created job (cascades skills/interactions)."""
        with SessionLocal() as db:
            row = db.get(Job, UUID(str(job_id)))
            if row is not None:
                db.delete(row)
                db.commit()

    @pytest.fixture
    def auth_headers():
        """Register a temporary user and return auth headers."""
        uid = uuid4().hex[:8]
        email = f"test_{uid}@example.com"
        reg = client.post("/api/v1/auth/register", json={
            "email": email,
            "password": "TestPass123!",
            "role": "job_seeker",
        })
        assert reg.status_code == 201, reg.text
        token = reg.json()["access_token"]
        yield {"Authorization": f"Bearer {token}"}
        # Torn down after sample_job (its dependencies tear down first)
        _delete_account(email)

    @pytest.fixture
    def sample_job(auth_headers):
        """Create an employer and a published job, returning the job dict."""
        uid = uuid4().hex[:8]
        emp_email = f"employer_{uid}@example.com"
        emp = client.post("/api/v1/auth/register", json={
            "email": emp_email,
            "password": "EmpPass123!",
            "role": "employer",
        })
        emp_token = emp.json()["access_token"]
        emp_headers = {"Authorization": f"Bearer {emp_token}"}
        job_resp = client.post("/api/v1/jobs", headers=emp_headers, json={
            "title": "Test Engineer",
            "description": "Write tests",
            "location": "Remote",
            "employment_type": "full_time",
            "experience_level": "mid",
            "salary_min": 50000,
            "salary_max": 80000,
        })
        assert job_resp.status_code == 201, job_resp.text
        job = job_resp.json()
        yield job
        # Leftover fixture jobs would otherwise pollute the shared dev corpus
        # and the recommender feed tests (neutral-skill junk outranks real matches).
        _delete_job(job["id"])
        _delete_account(emp_email)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestInteractionLogging:

    def test_post_view_interaction_returns_202(self, auth_headers, sample_job):
        """Fire-and-forget event should return 202 immediately."""
        # Get current user id
        me = client.get("/api/v1/auth/me", headers=auth_headers)
        assert me.status_code == 200
        user_id = me.json()["id"]

        resp = client.post("/api/v1/interactions", headers=auth_headers, json={
            "user_id": user_id,
            "job_id": sample_job["id"],
            "event_type": "view",
            "metadata": {"source": "feed", "position": 1},
        })
        assert resp.status_code == 202, resp.text
        body = resp.json()
        assert body["status"] == "accepted"
        assert body["event_type"] == "view"

    def test_post_all_event_types(self, auth_headers, sample_job):
        """All InteractionType values should be accepted."""
        me = client.get("/api/v1/auth/me", headers=auth_headers)
        user_id = me.json()["id"]

        for event_type in ("view", "save", "apply", "dismiss", "ignore", "click"):
            resp = client.post("/api/v1/interactions", headers=auth_headers, json={
                "user_id": user_id,
                "job_id": sample_job["id"],
                "event_type": event_type,
            })
            assert resp.status_code == 202, f"Failed for event_type={event_type}: {resp.text}"

    def test_post_wrong_user_id_returns_403(self, auth_headers, sample_job):
        """A user cannot log interactions for another user."""
        resp = client.post("/api/v1/interactions", headers=auth_headers, json={
            "user_id": str(uuid4()),  # random — not the authenticated user
            "job_id": sample_job["id"],
            "event_type": "view",
        })
        assert resp.status_code == 403

    def test_post_nonexistent_job_returns_404(self, auth_headers):
        """Logging an event for a non-existent job should return 404."""
        me = client.get("/api/v1/auth/me", headers=auth_headers)
        user_id = me.json()["id"]
        resp = client.post("/api/v1/interactions", headers=auth_headers, json={
            "user_id": user_id,
            "job_id": str(uuid4()),
            "event_type": "view",
        })
        assert resp.status_code == 404

    def test_post_invalid_event_type_returns_422(self, auth_headers, sample_job):
        """Unknown event types should fail Pydantic validation."""
        me = client.get("/api/v1/auth/me", headers=auth_headers)
        user_id = me.json()["id"]
        resp = client.post("/api/v1/interactions", headers=auth_headers, json={
            "user_id": user_id,
            "job_id": sample_job["id"],
            "event_type": "UNKNOWN_EVENT",
        })
        assert resp.status_code == 422

    def test_post_unauthenticated_returns_403_or_401(self, sample_job):
        """Unauthenticated requests must be rejected."""
        resp = client.post("/api/v1/interactions", json={
            "user_id": str(uuid4()),
            "job_id": sample_job["id"],
            "event_type": "view",
        })
        assert resp.status_code in (401, 403)


class TestGetMyInteractions:

    def test_get_returns_list(self, auth_headers, sample_job):
        """GET /interactions/me should return a list (possibly empty)."""
        resp = client.get("/api/v1/interactions/me", headers=auth_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_get_includes_posted_event(self, auth_headers, sample_job):
        """An event logged synchronously should appear in GET /interactions/me.

        BackgroundTasks run synchronously in TestClient, so the row will be in the DB
        by the time we query.
        """
        import time
        me = client.get("/api/v1/auth/me", headers=auth_headers)
        user_id = me.json()["id"]

        client.post("/api/v1/interactions", headers=auth_headers, json={
            "user_id": user_id,
            "job_id": sample_job["id"],
            "event_type": "save",
            "metadata": {"source": "test"},
        })

        # BackgroundTasks in TestClient are synchronous; give a small buffer anyway
        time.sleep(0.1)

        resp = client.get("/api/v1/interactions/me", headers=auth_headers)
        assert resp.status_code == 200
        events = resp.json()
        event_types = [e["event_type"] for e in events]
        assert "save" in event_types

    def test_get_unauthenticated_returns_401(self):
        resp = client.get("/api/v1/interactions/me")
        assert resp.status_code in (401, 403)
