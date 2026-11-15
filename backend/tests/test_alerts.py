"""Tests for saved-job alerts, digests, and the notification inbox.

Covers:
- GET/PUT /api/v1/alerts/settings (defaults + updates)
- GET      /api/v1/alerts/preview (dry-run matching, no writes)
- GET      /api/v1/notifications, unread-count, mark-read, read-all
- run_alert_cycle worker: digest/notification creation + (user_id, job_id) dedupe
- POST     /api/v1/jobs/{id}/apply promotes a saved row to applied (regression)
"""

from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.db import SessionLocal
from app.main import app
from app.models.alerts import JobAlert, JobAlertDigest, JobAlertItem, Notification
from app.models.application import Application
from app.models.enums import ApplicationStatus
from app.models.job import Job
from app.models.user import User
from app.services.job_alerts import run_alert_cycle

client = TestClient(app, raise_server_exceptions=False)


def _delete_job(job_id) -> None:
    with SessionLocal() as db:
        row = db.get(Job, UUID(str(job_id)))
        if row is not None:
            db.delete(row)
            db.commit()


def _delete_user(user_id) -> None:
    with SessionLocal() as db:
        row = db.get(User, UUID(str(user_id)))
        if row is not None:
            db.delete(row)
            db.commit()


def _register(role: str) -> dict:
    uid = uuid4().hex[:8]
    reg = client.post(
        "/api/v1/auth/register",
        json={
            "email": f"{role}_{uid}@example.com",
            "password": "Password123!",
            "role": role,
        },
    )
    assert reg.status_code == 201, reg.text
    body = reg.json()
    return {
        "headers": {"Authorization": f"Bearer {body['access_token']}"},
        "token": body["access_token"],
        "id": body["user"]["id"],
    }


@pytest.fixture
def seeker_user():
    user = _register("job_seeker")
    yield user
    _delete_user(user["id"])


@pytest.fixture
def employer_user():
    user = _register("employer")
    yield user
    _delete_user(user["id"])


def _create_job(employer: dict, *, title: str, description: str | None = None) -> dict:
    resp = client.post(
        "/api/v1/jobs",
        headers=employer["headers"],
        json={
            "title": title,
            "description": description
            or "Build and operate high-scale distributed backend services.",
            "requirements": "Strong Python, PostgreSQL, and distributed systems experience.",
            "employment_type": "full_time",
            "experience_level": "senior",
            "location": "Bengaluru, KA",
            "is_remote": True,
            "salary_min": 120000,
            "salary_max": 160000,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.fixture
def job_pair(employer_user):
    """A saved 'seed' job and a brand-new nearly identical posting."""
    title = f"Senior Backend Engineer {uuid4().hex[:4]}"
    seed = _create_job(employer_user, title=title)
    candidate = _create_job(employer_user, title=title)
    yield seed, candidate
    _delete_job(candidate["id"])
    _delete_job(seed["id"])


def _save_job(seeker: dict, job_id: str) -> dict:
    resp = client.post(f"/api/v1/jobs/{job_id}/save", headers=seeker["headers"])
    assert resp.status_code == 201, resp.text
    return resp.json()


class TestAlertSettings:

    def test_defaults_are_created_on_first_read(self, seeker_user):
        resp = client.get("/api/v1/alerts/settings", headers=seeker_user["headers"])
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["enabled"] is True
        assert body["email_enabled"] is True
        assert body["digest_frequency"] == "daily"
        assert body["min_score"] == 60.0
        assert body["max_items"] == 5

        with SessionLocal() as db:
            row = db.scalar(
                select(JobAlert).where(JobAlert.user_id == UUID(seeker_user["id"]))
            )
            assert row is not None

    def test_update_settings(self, seeker_user):
        client.get("/api/v1/alerts/settings", headers=seeker_user["headers"])
        resp = client.put(
            "/api/v1/alerts/settings",
            headers=seeker_user["headers"],
            json={
                "enabled": False,
                "email_enabled": False,
                "digest_frequency": "weekly",
                "min_score": 75,
                "max_items": 3,
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["enabled"] is False
        assert body["email_enabled"] is False
        assert body["digest_frequency"] == "weekly"
        assert body["min_score"] == 75.0
        assert body["max_items"] == 3

    def test_invalid_score_rejected(self, seeker_user):
        client.get("/api/v1/alerts/settings", headers=seeker_user["headers"])
        resp = client.put(
            "/api/v1/alerts/settings",
            headers=seeker_user["headers"],
            json={"min_score": 120},
        )
        assert resp.status_code == 422


class TestAlertPreview:

    def test_preview_returns_matches_without_writing(self, seeker_user, job_pair):
        seed, _candidate = job_pair
        _save_job(seeker_user, seed["id"])

        resp = client.get("/api/v1/alerts/preview", headers=seeker_user["headers"])
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["seeds_used"] >= 1
        assert body["candidates_scanned"] >= 1
        assert any(item["seed_job_id"] == seed["id"] for item in body["items"])

        with SessionLocal() as db:
            items = db.scalars(
                select(JobAlertItem).where(
                    JobAlertItem.user_id == UUID(seeker_user["id"])
                )
            ).all()
            assert items == []

    def test_preview_without_saved_jobs_is_empty(self, seeker_user):
        client.get("/api/v1/alerts/settings", headers=seeker_user["headers"])
        resp = client.get("/api/v1/alerts/preview", headers=seeker_user["headers"])
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["items"] == []
        assert body["seeds_used"] == 0


class TestAlertWorker:

    def test_worker_creates_digest_and_dedupes(self, seeker_user, job_pair):
        seed, candidate = job_pair
        _save_job(seeker_user, seed["id"])

        with SessionLocal() as db:
            result = run_alert_cycle(
                db,
                force=True,
                email_enabled=False,
                user_id=UUID(seeker_user["id"]),
            )
        assert result["enabled"] is True
        assert result["digests_sent"] == 1
        assert result["items_sent"] >= 1

        with SessionLocal() as db:
            items = db.scalars(
                select(JobAlertItem).where(
                    JobAlertItem.user_id == UUID(seeker_user["id"])
                )
            ).all()
            job_ids = {str(item.job_id) for item in items}
            assert candidate["id"] in job_ids

            digests = db.scalars(
                select(JobAlertDigest).where(
                    JobAlertDigest.user_id == UUID(seeker_user["id"])
                )
            ).all()
            assert len(digests) == 1

            notes = db.scalars(
                select(Notification).where(
                    Notification.user_id == UUID(seeker_user["id"])
                )
            ).all()
            assert len(notes) == len(items) >= 1

        # Second forced run: the same jobs must never be alerted twice.
        with SessionLocal() as db:
            second = run_alert_cycle(
                db,
                force=True,
                email_enabled=False,
                user_id=UUID(seeker_user["id"]),
            )
        assert second["digests_sent"] == 0
        assert second["items_sent"] == 0

        with SessionLocal() as db:
            items = db.scalars(
                select(JobAlertItem).where(
                    JobAlertItem.user_id == UUID(seeker_user["id"])
                )
            ).all()
            assert len(items) == len(job_ids)


class TestNotificationInbox:

    def test_inbox_and_read_flow(self, seeker_user, job_pair):
        seed, _candidate = job_pair
        _save_job(seeker_user, seed["id"])
        with SessionLocal() as db:
            run_alert_cycle(
                db,
                force=True,
                email_enabled=False,
                user_id=UUID(seeker_user["id"]),
            )

        inbox = client.get("/api/v1/notifications", headers=seeker_user["headers"])
        assert inbox.status_code == 200, inbox.text
        body = inbox.json()
        assert body["total"] >= 1
        assert body["unread"] >= 1
        first = body["items"][0]
        assert first["type"] == "job_alert"
        assert first["link"].startswith("/jobs/")

        count = client.get(
            "/api/v1/notifications/unread-count", headers=seeker_user["headers"]
        )
        assert count.status_code == 200
        assert count.json()["unread"] == body["unread"]

        marked = client.post(
            f"/api/v1/notifications/{first['id']}/read",
            headers=seeker_user["headers"],
        )
        assert marked.status_code == 200, marked.text
        assert marked.json()["read_at"] is not None

        all_read = client.post(
            "/api/v1/notifications/read-all", headers=seeker_user["headers"]
        )
        assert all_read.status_code == 200, all_read.text
        assert all_read.json()["marked"] >= 0

        after = client.get(
            "/api/v1/notifications/unread-count", headers=seeker_user["headers"]
        )
        assert after.json()["unread"] == 0

    def test_mark_unknown_notification_404(self, seeker_user):
        resp = client.post(
            f"/api/v1/notifications/{uuid4()}/read",
            headers=seeker_user["headers"],
        )
        assert resp.status_code == 404


class TestSaveThenApply:

    def test_applying_promotes_saved_row(self, seeker_user, job_pair):
        seed, _candidate = job_pair
        saved = _save_job(seeker_user, seed["id"])
        assert saved["status"] == "saved"

        resp = client.post(
            f"/api/v1/jobs/{seed['id']}/apply",
            headers=seeker_user["headers"],
            json={"cover_note": "Ready to move forward."},
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["status"] == "applied"
        assert resp.json()["cover_note"] == "Ready to move forward."

        with SessionLocal() as db:
            rows = db.scalars(
                select(Application).where(
                    Application.user_id == UUID(seeker_user["id"]),
                    Application.job_id == UUID(seed["id"]),
                )
            ).all()
            assert len(rows) == 1
            assert rows[0].status == ApplicationStatus.APPLIED
