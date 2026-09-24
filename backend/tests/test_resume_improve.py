"""§13 resume optimizer: deterministic ATS layer + anti-fabrication validator.

The validator is the safety rail: a rewrite citing a skill outside the
candidate's evidence (and outside the labeled JD gap list) is dropped and
counted — the LLM never gets to invent demonstrated skills.
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
from app.services import resume_improve

client = TestClient(app, raise_server_exceptions=False)

SAMPLE_RESUME = """\
Jane Doe
jane@example.com | +1 555 123 4567

Summary
Backend engineer with 4 years of experience.

Experience
- Built REST APIs with FastAPI serving 20k daily users
- Reduced p95 latency by 38% through query tuning
- Mentored 3 junior engineers

Projects
- Inventory service: FastAPI + PostgreSQL pipeline

Skills
Python, FastAPI, SQL, Git
"""


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
            "email": f"ri_{token}@example.com",
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
        yield {"id": str(job.id)}


class TestAtsReport:

    def test_full_report_passes(self):
        report = resume_improve.ats_report(
            SAMPLE_RESUME,
            jd_required=["FastAPI", "PostgreSQL", "missingtool"],
        )
        statuses = {c["name"]: c["status"] for c in report["checks"]}
        assert statuses["section_summary"] == "PASS"
        assert statuses["section_experience"] == "PASS"
        assert statuses["section_projects"] == "PASS"
        assert statuses["section_skills"] == "PASS"
        assert statuses["contact_block"] == "PASS"
        assert statuses["quantified_bullets"] == "PASS"  # 2/3 bullets have digits
        assert report["missing_keywords"] == ["missingtool"]
        assert report["keyword_coverage"] == pytest.approx(0.667, abs=1e-3)
        assert report["bullet_count"] >= 3
        assert 0.0 <= report["ats_score"] <= 100.0

    def test_empty_resume_fails(self):
        report = resume_improve.ats_report("", jd_required=["Python"])
        statuses = {c["name"]: c["status"] for c in report["checks"]}
        assert statuses["section_summary"] == "FAIL"
        assert statuses["length"] == "FAIL"
        assert report["missing_keywords"] == ["Python"]
        assert report["weak_evidence"] == []

    def test_weak_evidence_when_only_in_skills_list(self):
        report = resume_improve.ats_report(
            SAMPLE_RESUME,
            jd_required=["Git"],  # present in Skills section, never in a bullet
        )
        assert "Git" in report["weak_evidence"]


class TestAntiFabrication:

    ORIGINAL = "Built REST APIs with FastAPI serving 20k daily users"

    def test_drops_skill_outside_evidence(self):
        kept, violations = resume_improve.validate_suggestions(
            [{
                "bullet": self.ORIGINAL,
                "issues": ["no metric"],
                "suggestion": "Deployed services to Kubernetes, cutting costs 20%",
            }],
            original_bullets=[self.ORIGINAL],
            allowed_tokens={"fastapi"},
            lexicon={"kubernetes", "fastapi"},
        )
        assert kept == []
        assert len(violations) == 1
        assert violations[0]["violation"] == "skill_not_in_evidence"
        assert "kubernetes" in violations[0]["tokens"]

    def test_keeps_grounded_rewrite(self):
        kept, violations = resume_improve.validate_suggestions(
            [{
                "bullet": self.ORIGINAL,
                "issues": ["ok"],
                "suggestion": "Built REST APIs with FastAPI serving 20k daily users [metric]",
            }],
            original_bullets=[self.ORIGINAL],
            allowed_tokens={"fastapi"},
            lexicon={"kubernetes", "fastapi"},
        )
        assert len(kept) == 1
        assert kept[0]["status"] == "grounded"
        assert violations == []

    def test_gap_skills_are_allowed_as_context(self):
        """JD gaps are labeled 'do not claim' but may be referenced."""
        kept, violations = resume_improve.validate_suggestions(
            [{
                "bullet": self.ORIGINAL,
                "issues": [],
                "suggestion": "Next: build a Dockerized FastAPI service",
            }],
            original_bullets=[self.ORIGINAL],
            allowed_tokens={"fastapi", "docker"},  # docker = gap
            lexicon={"docker", "fastapi"},
        )
        assert len(kept) == 1
        assert violations == []

    def test_drops_rewrite_citing_a_bullet_that_does_not_exist(self):
        kept, violations = resume_improve.validate_suggestions(
            [{
                "bullet": "Led a 50-person org restructuring",  # fabricated span
                "issues": [],
                "suggestion": "Led a 50-person org restructuring",
            }],
            original_bullets=[self.ORIGINAL],
            allowed_tokens=set(),
            lexicon=set(),
        )
        assert kept == []
        assert violations[0]["violation"] == "bullet_not_in_resume"

    def test_skill_lexicon_from_parser(self):
        lexicon = resume_improve.skill_lexicon()
        assert "python" in lexicon
        assert "javascript" in lexicon


class TestOptimizeApi:

    def test_endpoint_returns_report_and_disclaimer(self, seeker, corpus_job):
        resp = client.post(
            f"/api/v1/jobs/{corpus_job['id']}/resume-optimize",
            headers=seeker["headers"],
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["job_id"] == corpus_job["id"]
        assert "checks" in data["ats"]
        assert 0.0 <= data["ats"]["ats_score"] <= 100.0
        assert isinstance(data["suggestions"], list)
        assert isinstance(data["violations_dropped"], int)
        assert isinstance(data["llm_used"], bool)
        assert "never add a skill" in data["disclaimer"].lower()

    def test_endpoint_requires_auth(self, corpus_job):
        resp = client.post(f"/api/v1/jobs/{corpus_job['id']}/resume-optimize")
        assert resp.status_code in (401, 403)

    def test_unknown_job_404(self, seeker):
        resp = client.post(
            f"/api/v1/jobs/{uuid4()}/resume-optimize",
            headers=seeker["headers"],
        )
        assert resp.status_code == 404
