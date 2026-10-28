"""Tests for the Employer API (plan §E0: company profile + posting lifecycle).

Covers:
- GET    /api/v1/employer/company        (404 when the account has no company)
- POST   /api/v1/employer/company        (creates; 409 when one already exists)
- PUT    /api/v1/employer/company        (partial update; "" clears optionals)
- PATCH  /api/v1/employer/postings/{id}/status (lifecycle + ownership 403/404)
- POST   /api/v1/employer/postings/{id}/duplicate (DRAFT clone carrying skills)
- role protection: JOB_SEEKER is refused on every employer endpoint
"""

from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.db import SessionLocal
from app.main import app
from app.models.job import Job
from app.models.user import User

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


def _register(role: str, company_name: str | None = None) -> dict:
    uid = uuid4().hex[:8]
    payload = {
        "email": f"{role}_{uid}@example.com",
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
        "token": body["access_token"],
        "id": body["user"]["id"],
        "email": payload["email"],
    }


@pytest.fixture
def employer_with_company():
    """Employer registered WITH a company (the normal signup path)."""
    emp = _register("employer", company_name=f"Labs {uuid4().hex[:6]}")
    yield emp
    _delete_user(emp["id"])


@pytest.fixture
def employer_without_company():
    """Employer who signed up without naming a company."""
    emp = _register("employer")
    yield emp
    _delete_user(emp["id"])


@pytest.fixture
def other_employer():
    emp = _register("employer", company_name=f"Rival {uuid4().hex[:6]}")
    yield emp
    _delete_user(emp["id"])


@pytest.fixture
def seeker():
    user = _register("job_seeker")
    yield user
    _delete_user(user["id"])


def _make_job(employer: dict, with_skills: bool = True) -> dict:
    payload = {
        "title": f"Platform Engineer {uuid4().hex[:4]}",
        "description": "Own the deployment platform and developer tooling.",
        "requirements": "Kubernetes and Terraform in production.",
        "employment_type": "full_time",
        "experience_level": "mid",
        "location": "Bengaluru, India",
        "is_remote": True,
        "salary_min": 1500000,
        "salary_max": 2400000,
        "salary_currency": "INR",
    }
    if with_skills:
        payload["skills"] = [
            {"skill_name": "Kubernetes", "is_required": True, "importance_weight": 2.0},
            {"skill_name": "Terraform", "is_required": False, "importance_weight": 1.0},
        ]
    resp = client.post("/api/v1/jobs", headers=employer["headers"], json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


class TestCompanyProfile:
    def test_get_company_404_when_none_exists(self, employer_without_company):
        resp = client.get("/api/v1/employer/company", headers=employer_without_company["headers"])
        assert resp.status_code == 404

    def test_register_with_company_name_returns_it(self, employer_with_company):
        resp = client.get("/api/v1/employer/company", headers=employer_with_company["headers"])
        assert resp.status_code == 200
        body = resp.json()
        assert body["name"].startswith("Labs ")
        assert body["slug"]
        assert body["open_postings"] == 0

    def test_create_company_then_read_back(self, employer_without_company):
        h = employer_without_company["headers"]
        created = client.post(
            "/api/v1/employer/company",
            headers=h,
            json={"name": "Acme Talent Co", "location": "Pune, India"},
        )
        assert created.status_code == 201, created.text
        assert created.json()["name"] == "Acme Talent Co"

        read = client.get("/api/v1/employer/company", headers=h)
        assert read.status_code == 200
        assert read.json()["location"] == "Pune, India"

    def test_create_company_conflicts_when_one_exists(self, employer_with_company):
        resp = client.post(
            "/api/v1/employer/company",
            headers=employer_with_company["headers"],
            json={"name": "Second Company"},
        )
        assert resp.status_code == 409

    def test_create_company_requires_name(self, employer_without_company):
        resp = client.post(
            "/api/v1/employer/company",
            headers=employer_without_company["headers"],
            json={"description": "no name given"},
        )
        assert resp.status_code == 422

    def test_update_is_partial_and_blank_clears_optionals(self, employer_with_company):
        h = employer_with_company["headers"]

        # seed some optional fields
        seeded = client.put(
            "/api/v1/employer/company",
            headers=h,
            json={"website": "https://example.com", "industry": "fintech"},
        )
        assert seeded.status_code == 200, seeded.text
        assert seeded.json()["website"] == "https://example.com"

        # update only location; name/website must survive
        updated = client.put(
            "/api/v1/employer/company",
            headers=h,
            json={"location": "Hyderabad, India"},
        )
        assert updated.status_code == 200
        body = updated.json()
        assert body["location"] == "Hyderabad, India"
        assert body["website"] == "https://example.com"
        assert body["name"].startswith("Labs ")

        # blank string clears an optional field
        cleared = client.put(
            "/api/v1/employer/company",
            headers=h,
            json={"industry": ""},
        )
        assert cleared.status_code == 200
        assert cleared.json()["industry"] is None


class TestPostingLifecycle:
    def test_status_transition_published_to_closed_and_back(self, employer_with_company):
        h = employer_with_company["headers"]
        job = _make_job(employer_with_company)
        assert job["status"] == "published"

        closed = client.patch(
            f"/api/v1/employer/postings/{job['id']}/status",
            headers=h,
            json={"status": "closed"},
        )
        assert closed.status_code == 200, closed.text
        assert closed.json()["status"] == "closed"

        reopened = client.patch(
            f"/api/v1/employer/postings/{job['id']}/status",
            headers=h,
            json={"status": "published"},
        )
        assert reopened.status_code == 200
        assert reopened.json()["status"] == "published"
        _delete_job(job["id"])

    def test_status_change_rejected_for_non_owner(self, employer_with_company, other_employer):
        job = _make_job(employer_with_company)
        resp = client.patch(
            f"/api/v1/employer/postings/{job['id']}/status",
            headers=other_employer["headers"],
            json={"status": "closed"},
        )
        assert resp.status_code == 403
        _delete_job(job["id"])

    def test_status_change_404_for_unknown_posting(self, employer_with_company):
        resp = client.patch(
            f"/api/v1/employer/postings/{uuid4()}/status",
            headers=employer_with_company["headers"],
            json={"status": "closed"},
        )
        assert resp.status_code == 404

    def test_duplicate_creates_draft_clone_with_skills(self, employer_with_company):
        h = employer_with_company["headers"]
        job = _make_job(employer_with_company, with_skills=True)

        dup = client.post(f"/api/v1/employer/postings/{job['id']}/duplicate", headers=h)
        assert dup.status_code == 201, dup.text
        copy = dup.json()

        assert copy["id"] != job["id"]
        assert copy["status"] == "draft"
        assert copy["title"].startswith(job["title"])
        assert copy["applicant_count"] == 0
        # skills carried over
        assert {s["skill_name"] for s in copy["skills"]} == {
            s["skill_name"] for s in job["skills"]
        }
        _delete_job(copy["id"])
        _delete_job(job["id"])

    def test_duplicate_rejected_for_non_owner(self, employer_with_company, other_employer):
        job = _make_job(employer_with_company)
        resp = client.post(
            f"/api/v1/employer/postings/{job['id']}/duplicate",
            headers=other_employer["headers"],
        )
        assert resp.status_code == 403
        _delete_job(job["id"])


class TestPostingPipeline:
    """E1: GET /employer/postings/{id}/pipeline funnel aggregates."""

    def _pipe(self, job_id: str, headers: dict) -> dict:
        resp = client.get(f"/api/v1/employer/postings/{job_id}/pipeline", headers=headers)
        assert resp.status_code == 200, resp.text
        return resp.json()

    def test_pipeline_is_zero_for_fresh_posting(self, employer_with_company):
        job = _make_job(employer_with_company)
        body = self._pipe(job["id"], employer_with_company["headers"])

        assert body["job_id"] == job["id"]
        assert body["title"] == job["title"]
        assert body["status"] == "published"
        assert body["total"] == 0
        assert body["counts"] == {
            "applied": 0,
            "viewed": 0,
            "shortlisted": 0,
            "interview": 0,
            "rejected": 0,
            "offer": 0,
            "saved": 0,
        }
        assert body["recent_7d"] == 0
        assert body["days_open"] >= 1
        assert body["applications_per_day"] == 0.0
        _delete_job(job["id"])

    def test_pipeline_counts_apply_then_stage_move(self, employer_with_company, seeker):
        h = employer_with_company["headers"]
        job = _make_job(employer_with_company)

        apply = client.post(
            f"/api/v1/jobs/{job['id']}/apply",
            headers=seeker["headers"],
            json={"cover_note": "I would love to work on your platform."},
        )
        assert apply.status_code == 201, apply.text
        app_id = apply.json()["id"]

        body = self._pipe(job["id"], h)
        assert body["total"] == 1
        assert body["counts"]["applied"] == 1
        assert body["recent_7d"] == 1

        moved = client.patch(
            f"/api/v1/employer/applications/{app_id}/status",
            headers=h,
            json={"status": "shortlisted"},
        )
        assert moved.status_code == 200, moved.text

        body = self._pipe(job["id"], h)
        assert body["total"] == 1  # total never changes on a stage move
        assert body["counts"]["applied"] == 0
        assert body["counts"]["shortlisted"] == 1

        _delete_job(job["id"])

    def test_pipeline_rejected_for_non_owner(self, employer_with_company, other_employer):
        job = _make_job(employer_with_company)
        resp = client.get(
            f"/api/v1/employer/postings/{job['id']}/pipeline",
            headers=other_employer["headers"],
        )
        assert resp.status_code == 403
        _delete_job(job["id"])

    def test_pipeline_rejected_for_job_seeker(self, seeker, employer_with_company):
        job = _make_job(employer_with_company)
        resp = client.get(
            f"/api/v1/employer/postings/{job['id']}/pipeline",
            headers=seeker["headers"],
        )
        assert resp.status_code == 403
        _delete_job(job["id"])

    def test_pipeline_404_for_unknown_posting(self, employer_with_company):
        resp = client.get(
            f"/api/v1/employer/postings/{uuid4()}/pipeline",
            headers=employer_with_company["headers"],
        )
        assert resp.status_code == 404


class TestPostingTalent:
    """E2: GET /employer/postings/{id}/talent reverse-match ranking."""

    def _talent(self, job_id: str, headers: dict) -> dict:
        resp = client.get(f"/api/v1/employer/postings/{job_id}/talent", headers=headers)
        assert resp.status_code == 200, resp.text
        return resp.json()

    def _apply(self, job_id: str, seeker: dict, note: str = "hello") -> str:
        resp = client.post(
            f"/api/v1/jobs/{job_id}/apply",
            headers=seeker["headers"],
            json={"cover_note": note},
        )
        assert resp.status_code == 201, resp.text
        return resp.json()["id"]

    def test_talent_ranks_only_actual_applicants_with_explainable_fit(
        self, employer_with_company, seeker
    ):
        h = employer_with_company["headers"]
        job = _make_job(employer_with_company, with_skills=True)
        app_id = self._apply(job["id"], seeker)

        body = self._talent(job["id"], h)
        assert body["job_id"] == job["id"]
        assert body["total_applicants"] == 1
        assert body["scored"] == 1
        assert len(body["candidates"]) == 1

        cand = body["candidates"][0]
        assert cand["application_id"] == app_id
        assert cand["status"] == "applied"
        # privacy: only applicants are ever ranked — this row is the seeker
        assert cand["email"] == seeker["email"]
        # explainable fit: score in range + all eight components present
        assert 0.0 <= cand["fit_score"] <= 100.0
        assert set(cand["components"]) == {
            "semantic",
            "skill",
            "experience",
            "education",
            "project",
            "location",
            "salary",
            "interest",
        }
        # a fresh seeker holds none of the job's required skills
        # (Terraform is nice-to-have in the fixture, so only the required
        # Kubernetes lands in missing_required)
        assert cand["matched_skills"] == []
        assert "Kubernetes" in cand["missing_required"]
        assert "Terraform" not in cand["missing_required"]

        _delete_job(job["id"])

    def test_talent_is_sorted_by_fit_descending(self, employer_with_company, seeker):
        # two applicants; ranking must be non-increasing by fit_score
        job = _make_job(employer_with_company, with_skills=True)
        self._apply(job["id"], seeker)
        body = self._talent(job["id"], employer_with_company["headers"])
        scores = [c["fit_score"] for c in body["candidates"]]
        assert scores == sorted(scores, reverse=True)
        _delete_job(job["id"])

    def test_talent_ranks_multiple_applicants(self, employer_with_company, seeker):
        job = _make_job(employer_with_company, with_skills=True)
        self._apply(job["id"], seeker)
        other = _register("job_seeker")
        try:
            self._apply(job["id"], other)
            body = self._talent(job["id"], employer_with_company["headers"])
            assert body["total_applicants"] == 2
            assert body["scored"] == 2
            assert len(body["candidates"]) == 2
        finally:
            _delete_user(other["id"])
            _delete_job(job["id"])

    def test_talent_empty_for_posting_without_applicants(self, employer_with_company):
        job = _make_job(employer_with_company)
        body = self._talent(job["id"], employer_with_company["headers"])
        assert body["total_applicants"] == 0
        assert body["candidates"] == []
        _delete_job(job["id"])

    def test_talent_rejected_for_non_owner(self, employer_with_company, other_employer):
        job = _make_job(employer_with_company)
        resp = client.get(
            f"/api/v1/employer/postings/{job['id']}/talent",
            headers=other_employer["headers"],
        )
        assert resp.status_code == 403
        _delete_job(job["id"])

    def test_talent_rejected_for_job_seeker(self, seeker, employer_with_company):
        job = _make_job(employer_with_company)
        resp = client.get(
            f"/api/v1/employer/postings/{job['id']}/talent",
            headers=seeker["headers"],
        )
        assert resp.status_code == 403
        _delete_job(job["id"])


class TestPostingInsights:
    """E3: GET /employer/postings/{id}/insights — JD health, benchmark, gaps."""

    def _insights(self, job_id: str, headers: dict) -> dict:
        resp = client.get(f"/api/v1/employer/postings/{job_id}/insights", headers=headers)
        assert resp.status_code == 200, resp.text
        return resp.json()

    def test_insights_reports_health_benchmark_and_market(self, employer_with_company):
        h = employer_with_company["headers"]
        job = _make_job(employer_with_company, with_skills=True)

        body = self._insights(job["id"], h)
        assert body["job_id"] == job["id"]
        assert body["title"] == job["title"]

        # --- JD health: structured checks, score in range ---
        health = body["jd_health"]
        assert 0.0 <= health["score"] <= 100.0
        labels = [c["label"] for c in health["checks"]]
        assert "Salary range" in labels
        assert "Skills tagged" in labels
        assert "Job family" in labels
        by_label = {c["label"]: c for c in health["checks"]}
        # the fixture posts a salary and a title in band
        assert by_label["Salary range"]["ok"] is True
        # ...but only two skills (Kubernetes + Terraform) → 3+ check fails
        assert by_label["Skills tagged"]["ok"] is False
        # fixture posts no family
        assert by_label["Job family"]["ok"] is False

        # --- benchmark: family-less posting falls back to all-market peers ---
        bench = body["benchmark"]
        assert bench is not None
        assert bench["peer_jobs"] >= 1
        if bench["midpoint_percentile"] is not None:
            assert 0.0 <= bench["midpoint_percentile"] <= 100.0
        if bench["remote_share"] is not None:
            assert 0.0 <= bench["remote_share"] <= 1.0

        # --- supply/demand: arithmetic + privacy (aggregates only) ---
        rows = {r["skill"]: r for r in body["required_skill_market"]}
        assert "Kubernetes" in rows  # required in the fixture
        assert "Terraform" not in rows  # nice-to-have is not "required"
        k8s = rows["Kubernetes"]
        assert k8s["gap"] == k8s["jobs_requiring"] - k8s["seekers_holding"]
        # response contains counts only — never a person
        assert set(k8s) == {"skill", "jobs_requiring", "seekers_holding", "gap"}

        assert len(body["family_top_demand"]) > 0
        _delete_job(job["id"])

    def test_insights_flags_missing_salary_range(self, employer_with_company):
        resp = client.post(
            "/api/v1/jobs",
            headers=employer_with_company["headers"],
            json={
                "title": f"No Salary Role {uuid4().hex[:4]}",
                "description": "A role that does not disclose its compensation band at all.",
                "employment_type": "full_time",
                "experience_level": "entry",
                "location": "Remote, India",
                "is_remote": True,
            },
        )
        assert resp.status_code == 201, resp.text
        job = resp.json()

        body = self._insights(job["id"], employer_with_company["headers"])
        by_label = {c["label"]: c for c in body["jd_health"]["checks"]}
        assert by_label["Salary range"]["ok"] is False
        # no salary on this posting → no percentile, even if peers have pay
        if body["benchmark"] is not None:
            assert body["benchmark"]["midpoint_percentile"] is None
        _delete_job(job["id"])

    def test_insights_rejected_for_non_owner(self, employer_with_company, other_employer):
        job = _make_job(employer_with_company)
        resp = client.get(
            f"/api/v1/employer/postings/{job['id']}/insights",
            headers=other_employer["headers"],
        )
        assert resp.status_code == 403
        _delete_job(job["id"])

    def test_insights_rejected_for_job_seeker(self, seeker, employer_with_company):
        job = _make_job(employer_with_company)
        resp = client.get(
            f"/api/v1/employer/postings/{job['id']}/insights",
            headers=seeker["headers"],
        )
        assert resp.status_code == 403
        _delete_job(job["id"])

    def test_insights_404_for_unknown_posting(self, employer_with_company):
        resp = client.get(
            f"/api/v1/employer/postings/{uuid4()}/insights",
            headers=employer_with_company["headers"],
        )
        assert resp.status_code == 404


class TestPostingPerformance:
    """E4: GET /employer/postings/{id}/performance — series, conversion, health."""

    def _perf(self, job_id: str, headers: dict) -> dict:
        resp = client.get(f"/api/v1/employer/postings/{job_id}/performance", headers=headers)
        assert resp.status_code == 200, resp.text
        return resp.json()

    def test_performance_idle_posting_has_empty_zero_filled_series(self, employer_with_company):
        job = _make_job(employer_with_company)
        body = self._perf(job["id"], employer_with_company["headers"])

        assert body["job_id"] == job["id"]
        assert body["total"] == 0
        assert body["health"] == "idle"
        assert body["recent_7d"] == 0
        assert body["days_since_last_application"] is None
        assert body["avg_days_to_last_move"] is None

        # exactly 30 zero-filled days, ascending ISO dates
        assert len(body["series"]) == 30
        assert all(d["count"] == 0 for d in body["series"])
        dates = [d["date"] for d in body["series"]]
        assert dates == sorted(dates)

        conv = body["conversion"]
        assert conv == {
            "viewed_rate": 0.0,
            "shortlist_rate": 0.0,
            "interview_rate": 0.0,
            "offer_rate": 0.0,
            "rejection_rate": 0.0,
        }
        _delete_job(job["id"])

    def test_performance_counts_applications_moves_and_conversion(
        self, employer_with_company, seeker
    ):
        h = employer_with_company["headers"]
        job = _make_job(employer_with_company)

        apply = client.post(
            f"/api/v1/jobs/{job['id']}/apply",
            headers=seeker["headers"],
            json={"cover_note": "hi"},
        )
        assert apply.status_code == 201, apply.text
        app_id = apply.json()["id"]

        moved = client.patch(
            f"/api/v1/employer/applications/{app_id}/status",
            headers=h,
            json={"status": "shortlisted"},
        )
        assert moved.status_code == 200, moved.text

        body = self._perf(job["id"], h)
        assert body["total"] == 1
        assert body["health"] == "steady"  # exactly 1 in the last 7 days
        assert body["recent_7d"] == 1
        assert body["days_since_last_application"] == 0
        assert body["avg_days_to_last_move"] is not None
        assert body["avg_days_to_last_move"] >= 0.0

        # today's bucket carries the application
        assert body["series"][-1]["count"] == 1

        conv = body["conversion"]
        assert conv["viewed_rate"] == 100.0  # shortlisted counts as viewed-or-beyond
        assert conv["shortlist_rate"] == 100.0
        assert conv["interview_rate"] == 0.0
        assert conv["offer_rate"] == 0.0
        assert conv["rejection_rate"] == 0.0

        _delete_job(job["id"])

    def test_performance_rejected_for_non_owner(self, employer_with_company, other_employer):
        job = _make_job(employer_with_company)
        resp = client.get(
            f"/api/v1/employer/postings/{job['id']}/performance",
            headers=other_employer["headers"],
        )
        assert resp.status_code == 403
        _delete_job(job["id"])

    def test_performance_rejected_for_job_seeker(self, seeker, employer_with_company):
        job = _make_job(employer_with_company)
        resp = client.get(
            f"/api/v1/employer/postings/{job['id']}/performance",
            headers=seeker["headers"],
        )
        assert resp.status_code == 403
        _delete_job(job["id"])

    def test_performance_404_for_unknown_posting(self, employer_with_company):
        resp = client.get(
            f"/api/v1/employer/postings/{uuid4()}/performance",
            headers=employer_with_company["headers"],
        )
        assert resp.status_code == 404


class TestWhatIfRelaxer:
    """E5: POST /employer/postings/{id}/whatif — simulate relaxations."""

    def _whatif(self, job_id: str, headers: dict, payload: dict | None = None):
        return client.post(
            f"/api/v1/employer/postings/{job_id}/whatif",
            headers=headers,
            json=payload if payload is not None else {},
        )

    def test_baseline_echoes_current_state_and_ranks_levers(self, employer_with_company):
        h = employer_with_company["headers"]
        job = _make_job(employer_with_company, with_skills=True)

        resp = self._whatif(job["id"], h, {})
        assert resp.status_code == 200, resp.text
        body = resp.json()

        assert body["job_id"] == job["id"]
        assert body["reach_before"] == body["reach_after"]  # nothing dropped
        assert 0 <= body["reach_after"] <= body["total_seekers"]
        assert body["jd_health_before"] == body["jd_health_after"]
        assert body["avg_fit_before"] is None  # no applicants yet
        assert body["avg_fit_after"] is None
        assert body["applicants_scored"] == 0

        # baseline ranks each required skill as a lever, gain >= 0
        # (fewer constraints can only grow reach — set monotonicity)
        assert len(body["drop_options"]) == 1
        opt = body["drop_options"][0]
        assert opt["skill"] == "Kubernetes"
        assert opt["gain"] == opt["reach_if_dropped"] - body["reach_before"]
        assert opt["gain"] >= 0

        assert any("Baseline" in e for e in body["effects"])
        _delete_job(job["id"])

    def test_dropping_required_skill_grows_reach_and_never_touches_posting(
        self, employer_with_company
    ):
        h = employer_with_company["headers"]
        job = _make_job(employer_with_company, with_skills=True)

        resp = self._whatif(job["id"], h, {"drop_required_skills": ["Kubernetes"]})
        assert resp.status_code == 200, resp.text
        body = resp.json()

        assert body["reach_after"] >= body["reach_before"]
        assert body["applied"]["drop_required_skills"] == ["Kubernetes"]
        # Kubernetes was the only required skill → nothing left to relax
        assert body["drop_options"] == []
        # dropping the LAST required skill fails the "Required skills" JD check
        assert body["jd_health_after"] < body["jd_health_before"]
        assert body["effects"]

        # simulation only: the real posting still requires Kubernetes
        detail = client.get(f"/api/v1/jobs/{job['id']}", headers=h)
        assert detail.status_code == 200
        required_now = [
            s["skill_name"] for s in detail.json()["skills"] if s["is_required"]
        ]
        assert required_now == ["Kubernetes"]

        _delete_job(job["id"])

    def test_whatif_rejects_unknown_drop_and_inverted_salary(self, employer_with_company):
        h = employer_with_company["headers"]
        job = _make_job(employer_with_company, with_skills=True)

        resp = self._whatif(job["id"], h, {"drop_required_skills": ["COBOL"]})
        assert resp.status_code == 400

        resp = self._whatif(job["id"], h, {"salary_min": 9_999_999})
        assert resp.status_code == 400  # exceeds the posting's salary_max

        _delete_job(job["id"])

    def test_whatif_scores_own_applicants_before_and_after(
        self, employer_with_company, seeker
    ):
        h = employer_with_company["headers"]
        job = _make_job(employer_with_company, with_skills=True)
        apply = client.post(
            f"/api/v1/jobs/{job['id']}/apply",
            headers=seeker["headers"],
            json={"cover_note": "hi"},
        )
        assert apply.status_code == 201, apply.text

        resp = self._whatif(job["id"], h, {"drop_required_skills": ["Kubernetes"]})
        assert resp.status_code == 200, resp.text
        body = resp.json()

        assert body["applicants_scored"] == 1
        assert body["avg_fit_before"] is not None
        assert body["avg_fit_after"] is not None
        assert 0.0 <= body["avg_fit_before"] <= 100.0
        assert 0.0 <= body["avg_fit_after"] <= 100.0

        _delete_job(job["id"])

    def test_whatif_guards(self, employer_with_company, other_employer, seeker):
        job = _make_job(employer_with_company)

        resp = client.post(
            f"/api/v1/employer/postings/{job['id']}/whatif",
            headers=other_employer["headers"],
            json={},
        )
        assert resp.status_code == 403

        resp = client.post(
            f"/api/v1/employer/postings/{job['id']}/whatif",
            headers=seeker["headers"],
            json={},
        )
        assert resp.status_code == 403

        resp = client.post(
            f"/api/v1/employer/postings/{uuid4()}/whatif",
            headers=employer_with_company["headers"],
            json={},
        )
        assert resp.status_code == 404

        _delete_job(job["id"])


class TestRoleProtection:
    """JOB_SEEKER must never reach the employer surface."""

    @pytest.mark.parametrize(
        "method,path",
        [
            ("get", "/api/v1/employer/company"),
            ("post", "/api/v1/employer/company"),
            ("get", "/api/v1/employer/jobs"),
        ],
    )
    def test_job_seeker_is_forbidden(self, seeker, method, path):
        kwargs = {"headers": seeker["headers"]}
        if method == "post":
            kwargs["json"] = {"name": "Sneaky Co"}
        resp = getattr(client, method)(path, **kwargs)
        assert resp.status_code == 403

    def test_job_seeker_cannot_change_posting_status(self, seeker, employer_with_company):
        job = _make_job(employer_with_company)
        resp = client.patch(
            f"/api/v1/employer/postings/{job['id']}/status",
            headers=seeker["headers"],
            json={"status": "closed"},
        )
        assert resp.status_code == 403
        _delete_job(job["id"])
