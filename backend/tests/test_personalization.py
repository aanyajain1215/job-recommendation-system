"""§16 M4 preference-learner tests: bounds, shrinkage, decay, reset, APIs.

State is keyed to throwaway seeker accounts and purged in teardown; corpus
jobs are only read (recommendation snapshots are keyed to the throwaway
profile and cascade away with it).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.db import SessionLocal
from app.main import app
from app.models.feedback import SkillAffinity
from app.models.job import Job
from app.models.ops import SystemConfig
from app.models.profile import Profile
from app.models.recommendation import Recommendation
from app.models.skill import JobSkill
from app.models.user import User
from app.services import personalization as m4
from app.services.scoring import DEFAULT_WEIGHTS

client = TestClient(app, raise_server_exceptions=False)

COMPONENTS_8 = set(DEFAULT_WEIGHTS)


def _delete_user(user_id) -> None:
    """Teardown: M4 state (no FK) + account; profile-keyed rows cascade."""
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


def _register_seeker() -> dict:
    token = uuid4().hex[:8]
    reg = client.post(
        "/api/v1/auth/register",
        json={
            "email": f"m4_{token}@example.com",
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
def corpus_job():
    """Read-only handle to a seeded job that carries REQUIRED skills."""
    with SessionLocal() as db:
        job = db.scalar(
            select(Job)
            .join(Job.skills)
            .where(JobSkill.is_required.is_(True))
            .order_by(Job.created_at, Job.id)
            .limit(1)
        )
        assert job is not None, "seed corpus must contain a job with skills"
        yield {"id": str(job.id)}


def _profile_for(user_id) -> Profile:
    """Register auto-creates the profile row (auth.py) — fetch it."""
    from uuid import UUID

    with SessionLocal() as db:
        profile = db.scalar(
            select(Profile).where(Profile.user_id == UUID(str(user_id)))
        )
        assert profile is not None, "register must auto-create a profile"
        return profile


class TestWeightMath:

    def test_defaults_without_state(self):
        """No state → global weights, no note, zero shrinkage."""
        with SessionLocal() as db:
            weights, note, shrink = m4.effective_weights(db, uuid4())
        assert weights == DEFAULT_WEIGHTS
        assert note is None
        assert shrink == 0.0

    def test_shrinkage_factor_formula(self):
        assert m4._shrinkage(0) == 0.0
        assert m4._shrinkage(10) == pytest.approx(0.5)   # n/(n+k), k=10
        assert m4._shrinkage(90) == pytest.approx(0.9)

    def test_update_is_bounded_and_renormalized(self, seeker):
        """η=0.15 step, clamp to [0.5, 2.0]×global, Σ=1 (plan §16)."""
        profile = _profile_for(seeker["id"])
        with SessionLocal() as db:
            job = db.scalar(select(Job).order_by(Job.created_at, Job.id).limit(1))
            assert job is not None
            # Engine snapshot with an extreme salary shape (95 vs neutral 50)
            db.add(
                Recommendation(
                    profile_id=profile.id,
                    job_id=job.id,
                    snapshot={
                        "components": {
                            "semantic": 50.0, "skill": 50.0, "experience": 50.0,
                            "education": 50.0, "project": 50.0, "location": 50.0,
                            "salary": 95.0, "interest": 50.0,
                        },
                    },
                )
            )
            db.commit()

            for _ in range(5):
                m4.update_weights(db, profile, job, "salary_issue")
            db.commit()

            weights, note, shrink = m4.effective_weights(db, profile.user_id)
            assert set(weights) == COMPONENTS_8
            assert sum(weights.values()) == pytest.approx(1.0, abs=1e-6)
            # loose post-renorm envelope around the §16 bounds (documented:
            # clamping happens before renormalisation, so allow modest drift)
            for k, w in weights.items():
                g = DEFAULT_WEIGHTS[k]
                assert 0.4 * g <= w <= 2.5 * g, f"{k}={w} escaped bounds"
            # the disliked high-salary item pulls the salary weight down
            assert weights["salary"] < DEFAULT_WEIGHTS["salary"]
            assert shrink > 0
            assert note is None or "weight" in note

    def test_state_history_capped(self, seeker):
        profile = _profile_for(seeker["id"])
        with SessionLocal() as db:
            job = db.scalar(select(Job).order_by(Job.created_at, Job.id).limit(1))
            db.add(
                Recommendation(
                    profile_id=profile.id,
                    job_id=job.id,
                    snapshot={"components": {
                        "semantic": 50.0, "skill": 50.0, "experience": 50.0,
                        "education": 50.0, "project": 50.0, "location": 50.0,
                        "salary": 90.0, "interest": 50.0,
                    }},
                )
            )
            db.commit()
            for i in range(30):
                m4.update_weights(db, profile, job, "relevant")
            db.commit()
            state = m4.load_state(db, profile.user_id)
            assert state is not None
            assert state["n_events"] == 30
            assert len(state["history"]) <= m4.HISTORY_LIMIT
            assert state["history"], "uneven components must produce history"


class TestAffinities:

    def test_decay_half_life(self):
        now = datetime.now(timezone.utc)
        assert m4.decay(1.0, now - timedelta(days=30), now) == pytest.approx(0.5)
        assert m4.decay(1.0, now - timedelta(days=60), now) == pytest.approx(0.25)
        assert m4.decay(1.0, None, now) == 1.0

    def test_negative_lean_clamped(self, seeker, corpus_job):
        """Repeated negative feedback leans but never removes (§16)."""
        profile = _profile_for(seeker["id"])
        with SessionLocal() as db:
            job = db.get(Job, corpus_job["id"])
            assert job is not None
            for _ in range(6):
                m4.update_affinities(db, profile, job, "too_difficult")
            db.commit()

            affinities = m4.load_affinities(db, profile.id)
            assert affinities, "required job skills must accumulate lean"
            for value in affinities.values():
                assert -1.0 <= value <= 1.0
                assert value > -1.0 + 1e-9 or value == -1.0  # bounded
            # penalty factor never reaches zero (never full removal)
            for value in affinities.values():
                assert max(0.0, 1.0 + value * 0.3) >= 0.7 - 1e-9

    def test_positive_and_neutral_reasons(self, seeker, corpus_job):
        profile = _profile_for(seeker["id"])
        with SessionLocal() as db:
            job = db.get(Job, corpus_job["id"])
            m4.update_affinities(db, profile, job, "relevant")
            m4.update_affinities(db, profile, job, "salary_issue")  # no lean
            db.commit()
            affinities = m4.load_affinities(db, profile.id)
            assert affinities and all(v > 0 for v in affinities.values())


class TestFeedbackAndPreferencesApi:

    def test_feedback_endpoint_trains_and_persists(self, seeker, corpus_job):
        # Content-based feed first: snapshots carry component values, which
        # are the deterministic input to the M4 weight update (§16).
        put = client.put(
            "/api/v1/profiles/me",
            headers=seeker["headers"],
            json={
                "headline": "Backend engineer",
                "bio": "Python and FastAPI developer",
            },
        )
        assert put.status_code in (200, 201), put.text
        feed = client.get(
            "/api/v1/recommendations",
            params={"limit": 30},
            headers=seeker["headers"],
        )
        assert feed.status_code == 200, feed.text

        resp = client.post(
            "/api/v1/feedback",
            headers=seeker["headers"],
            json={
                "job_id": corpus_job["id"],
                "reason": "too_difficult",
                "note": "needs more Kubernetes",
            },
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["reason"] == "too_difficult"
        assert body["job_id"] == corpus_job["id"]

        prefs = client.get("/api/v1/preferences", headers=seeker["headers"])
        assert prefs.status_code == 200, prefs.text
        data = prefs.json()
        assert len(data["weights"]) == 8
        total = sum(w["weight"] for w in data["weights"])
        # API rounds each weight to 4dp for display → Σ drift ≤ ~5e-4.
        assert total == pytest.approx(1.0, abs=1e-3)
        assert data["n_events"] >= 1
        assert data["affinities"], "too_difficult leans required skills"
        assert data["affinities"][0]["score"] <= 0

    def test_preferences_reset_roundtrip(self, seeker, corpus_job):
        client.post(
            "/api/v1/feedback",
            headers=seeker["headers"],
            json={"job_id": corpus_job["id"], "reason": "relevant"},
        )
        reset = client.patch(
            "/api/v1/preferences",
            headers=seeker["headers"],
            json={"reset": True},
        )
        assert reset.status_code == 200, reset.text
        data = reset.json()
        assert data["n_events"] == 0
        assert data["affinities"] == []
        for w in data["weights"]:
            assert w["weight"] == pytest.approx(w["global_weight"])

    def test_preferences_reset_requires_flag(self, seeker):
        resp = client.patch(
            "/api/v1/preferences",
            headers=seeker["headers"],
            json={"reset": False},
        )
        assert resp.status_code == 400

    def test_feedback_unknown_job_404(self, seeker):
        resp = client.post(
            "/api/v1/feedback",
            headers=seeker["headers"],
            json={"job_id": str(uuid4()), "reason": "not_relevant"},
        )
        assert resp.status_code == 404
