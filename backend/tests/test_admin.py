"""§22 admin surface tests: role gate, transactional merge, Σ=1 config,
read-only ops endpoints, parse-failure retry, LLM kill switch.

Skills created here are purged in teardown; the shared corpus and JSONB
snapshots are never modified by these tests.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.db import SessionLocal
from app.main import app
from app.models.company import Company
from app.models.enums import EmploymentType, ExperienceLevel, JobStatus, UserRole
from app.models.job import Job
from app.models.moderation import ModerationFlag
from app.models.ops import SystemConfig
from app.models.profile import Profile
from app.models.skill import ProfileSkill, Skill
from app.models.skill_graph import SkillAlias
from app.models.user import User
from app.services.scoring import DEFAULT_WEIGHTS

client = TestClient(app, raise_server_exceptions=False)

ADMIN_ROUTES = [
    ("GET", "/api/v1/admin/overview"),
    ("GET", "/api/v1/admin/users"),
    ("GET", "/api/v1/admin/jobs"),
    ("GET", "/api/v1/admin/employers"),
    ("GET", "/api/v1/admin/moderation/flags"),
    ("GET", "/api/v1/admin/moderation/suspicious-jobs"),
    ("GET", "/api/v1/admin/moderation/suspicious-employers"),
    ("GET", "/api/v1/admin/skills"),
    ("GET", "/api/v1/admin/jobs/duplicates"),
    ("GET", "/api/v1/admin/llm-usage"),
    ("GET", "/api/v1/admin/parse-failures"),
    ("GET", "/api/v1/admin/config"),
    ("GET", "/api/v1/admin/models"),
]


def _delete_user(user_id) -> None:
    """Teardown: M4/M5 config rows (no FK) + account; profile cascades."""
    uid = UUID(str(user_id))
    with SessionLocal() as db:
        for key in (f"m4:{uid}", f"m5:{uid}"):
            row = db.get(SystemConfig, key)
            if row is not None:
                db.delete(row)
        user = db.get(User, uid)
        if user is not None:
            db.delete(user)
        db.commit()


def _register(prefix: str) -> dict:
    token = uuid4().hex[:8]
    email = f"{prefix}_{token}@example.com"
    reg = client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "Password123!",
            "role": "job_seeker",
        },
    )
    assert reg.status_code == 201, reg.text
    body = reg.json()
    return {
        "headers": {"Authorization": f"Bearer {body['access_token']}"},
        "id": body["user"]["id"],
        "email": email,
    }


def _promote(account: dict) -> None:
    with SessionLocal() as db:
        user = db.get(User, UUID(account["id"]))
        assert user is not None
        user.role = UserRole.ADMIN
        db.commit()


@pytest.fixture
def seeker():
    account = _register("sekker")
    yield account
    _delete_user(account["id"])


@pytest.fixture
def admin():
    account = _register("admintest")
    _promote(account)
    yield account
    _delete_user(account["id"])


@pytest.fixture
def merge_pair(admin):
    """Fresh source/target skills + source attached to a throwaway profile."""
    suffix = uuid4().hex[:8]
    source_name = f"NodeJSx{suffix}"
    target_name = f"Nodex{suffix}"
    with SessionLocal() as db:
        profile = db.scalar(select(Profile).where(Profile.user_id == UUID(admin["id"])))
        assert profile is not None
        source = Skill(name=source_name, category="programming")
        target = Skill(name=target_name, category="programming")
        db.add_all([source, target])
        db.flush()
        db.add(ProfileSkill(profile_id=profile.id, skill_id=source.id))
        db.add(SkillAlias(alias=f"nodejs-alias-{suffix}", skill_id=source.id))
        db.commit()
        ids = {
            "source_id": str(source.id),
            "target_id": str(target.id),
            "profile_id": str(profile.id),
            "source_name": source_name,
            "alias": f"nodejs-alias-{suffix}",
        }
    yield ids
    with SessionLocal() as db:
        for name in (source_name, target_name):
            skill = db.scalar(select(Skill).where(Skill.name == name))
            if skill is None:
                continue
            for ps in db.scalars(
                select(ProfileSkill).where(ProfileSkill.skill_id == skill.id)
            ).all():
                db.delete(ps)
            for al in db.scalars(
                select(SkillAlias).where(SkillAlias.skill_id == skill.id)
            ).all():
                db.delete(al)
            db.delete(skill)
        db.commit()


@pytest.fixture
def clean_weights():
    """Guaranteed removal of any admin weight override — runs even on failure
    so a mid-test abort can't leak custom weights into other test files."""
    yield
    with SessionLocal() as db:
        row = db.get(SystemConfig, "scoring_weights")
        if row is not None:
            db.delete(row)
            db.commit()


@pytest.fixture
def temp_job(admin):
    """A throwaway company + posting for moderation tests; purged after."""
    suffix = uuid4().hex[:8]
    with SessionLocal() as db:
        company = Company(
            name=f"Admin Test Co {suffix}",
            slug=f"admin-test-co-{suffix}",
            created_by_user_id=UUID(admin["id"]),
        )
        db.add(company)
        db.flush()
        job = Job(
            company_id=company.id,
            posted_by_user_id=UUID(admin["id"]),
            title=f"Platform Engineer {suffix}",
            description="Temporary posting created by the admin test suite.",
            employment_type=EmploymentType.FULL_TIME,
            experience_level=ExperienceLevel.MID,
            location="Remote",
            is_remote=True,
            status=JobStatus.DRAFT,
            source="native",
        )
        db.add(job)
        db.commit()
        ids = {"company_id": str(company.id), "job_id": str(job.id), "title": job.title}
    yield ids
    with SessionLocal() as db:
        job = db.get(Job, UUID(ids["job_id"]))
        if job is not None:
            db.delete(job)
        company = db.get(Company, UUID(ids["company_id"]))
        if company is not None:
            db.delete(company)
        db.commit()


def test_admin_routes_reject_non_admin(seeker):
    for method, path in ADMIN_ROUTES:
        resp = client.get(path, headers=seeker["headers"])
        assert resp.status_code == 403, f"{path} -> {resp.status_code}"

    resp = client.post(
        "/api/v1/admin/skills/merge",
        json={"source_id": str(uuid4()), "target_id": str(uuid4())},
        headers=seeker["headers"],
    )
    assert resp.status_code == 403


def test_skill_merge_is_transactional(admin, merge_pair):
    # invalid requests first
    same = client.post(
        "/api/v1/admin/skills/merge",
        json={"source_id": merge_pair["source_id"], "target_id": merge_pair["source_id"]},
        headers=admin["headers"],
    )
    assert same.status_code == 400

    missing = client.post(
        "/api/v1/admin/skills/merge",
        json={"source_id": str(uuid4()), "target_id": merge_pair["target_id"]},
        headers=admin["headers"],
    )
    assert missing.status_code == 404

    resp = client.post(
        "/api/v1/admin/skills/merge",
        json={"source_id": merge_pair["source_id"], "target_id": merge_pair["target_id"]},
        headers=admin["headers"],
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "merged"
    assert body["profile_skills"]["moved"] == 1
    assert body["source"]["name"] == merge_pair["source_name"]

    with SessionLocal() as db:
        source = db.get(Skill, UUID(merge_pair["source_id"]))
        target = db.get(Skill, UUID(merge_pair["target_id"]))
        assert source is None, "source skill must be absorbed"
        assert target is not None

        # profile row re-pointed, exactly once
        rows = db.scalars(
            select(ProfileSkill).where(
                ProfileSkill.profile_id == UUID(merge_pair["profile_id"]),
                ProfileSkill.skill_id == UUID(merge_pair["target_id"]),
            )
        ).all()
        assert len(rows) == 1

        # alias preserved: old alias + absorbed name both resolve to target
        alias_names = {
            a.alias
            for a in db.scalars(
                select(SkillAlias).where(
                    SkillAlias.skill_id == UUID(merge_pair["target_id"])
                )
            ).all()
        }
        assert merge_pair["alias"] in alias_names
        assert merge_pair["source_name"] in alias_names


def test_config_weights_require_sum_one(admin, clean_weights):
    bad_sum = {k: v for k, v in DEFAULT_WEIGHTS.items()}
    bad_sum["semantic"] = 0.50  # Σ = 1.20
    resp = client.put(
        "/api/v1/admin/config",
        json={"weights": bad_sum},
        headers=admin["headers"],
    )
    assert resp.status_code == 422
    assert "sum" in resp.json()["detail"]

    missing = dict(DEFAULT_WEIGHTS)
    missing.pop("salary")
    resp = client.put(
        "/api/v1/admin/config",
        json={"weights": missing},
        headers=admin["headers"],
    )
    assert resp.status_code == 422
    assert "salary" in resp.json()["detail"]

    valid = {k: v for k, v in DEFAULT_WEIGHTS.items()}
    valid["semantic"] = 0.35
    valid["skill"] = 0.20
    resp = client.put(
        "/api/v1/admin/config",
        json={"weights": valid},
        headers=admin["headers"],
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "saved"

    got = client.get("/api/v1/admin/config", headers=admin["headers"])
    assert got.status_code == 200
    cfg = got.json()
    assert cfg["source"] == "system_config"
    assert abs(cfg["sum"] - 1.0) < 1e-6
    by_component = {w["component"]: w["weight"] for w in cfg["weights"]}
    assert by_component["semantic"] == 0.35
    assert "enabled" in cfg["llm"]
    # cleanup: the clean_weights fixture deletes the row after the test


def test_admin_read_endpoints(admin):
    skills = client.get("/api/v1/admin/skills", headers=admin["headers"])
    assert skills.status_code == 200
    payload = skills.json()
    assert payload["total_skills"] >= 1
    assert payload["items"], "seeded corpus exposes skills"
    assert {"id", "name", "profiles", "jobs", "aliases"} <= set(payload["items"][0])

    filtered = client.get(
        "/api/v1/admin/skills", params={"q": "python"}, headers=admin["headers"]
    )
    assert filtered.status_code == 200
    assert all("python" in item["name"].lower() for item in filtered.json()["items"])

    dups = client.get("/api/v1/admin/jobs/duplicates", headers=admin["headers"])
    assert dups.status_code == 200
    dup_body = dups.json()
    assert dup_body["threshold"] == 0.92
    assert dup_body["jobs_examined"] >= 0
    assert isinstance(dup_body["pairs"], list)

    usage = client.get("/api/v1/admin/llm-usage", headers=admin["headers"])
    assert usage.status_code == 200
    usage_body = usage.json()
    assert {"calls", "prompt_tokens", "estimated_cost_usd"} <= set(
        usage_body["totals"]
    )
    assert "llm_enabled" in usage_body
    assert isinstance(usage_body["recent"], list)

    failures = client.get("/api/v1/admin/parse-failures", headers=admin["headers"])
    assert failures.status_code == 200
    assert isinstance(failures.json()["items"], list)

    models = client.get("/api/v1/admin/models", headers=admin["headers"])
    assert models.status_code == 200
    assert "items" in models.json()

    retry = client.post(
        f"/api/v1/admin/parse-failures/{uuid4()}/retry", headers=admin["headers"]
    )
    assert retry.status_code == 404


def test_admin_overview_shape(admin):
    resp = client.get("/api/v1/admin/overview", headers=admin["headers"])
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert "generated_at" in body
    assert {
        "total",
        "active",
        "job_seekers",
        "employers",
        "admins",
        "new_last_7d",
        "deactivated",
        "online_now",
        "active_today",
        "active_week",
        "active_month",
    } <= set(body["users"])
    assert body["users"]["total"] >= 1
    assert body["users"]["admins"] >= 1
    assert {"total", "with_resume"} <= set(body["profiles"])
    assert {
        "total",
        "verified",
        "unverified",
        "active_owners",
        "with_published_jobs",
        "new_last_7d",
    } <= set(body["companies"])
    assert {
        "total",
        "published",
        "draft",
        "closed",
        "archived",
        "new_last_7d",
    } <= set(body["jobs"])
    assert {
        "total",
        "last_7d",
        "by_status",
        "hires",
        "job_seekers_hired",
        "offers",
        "hires_last_30d",
        "applicants",
        "employers_with_hires",
        "hire_rate",
    } <= set(body["applications"])
    assert {
        "open_flags",
        "high_severity_flags",
        "flagged_jobs",
        "flagged_companies",
        "flagged_users",
        "resolved_last_7d",
    } <= set(body["moderation"])
    assert {"total", "embedded"} <= set(body["skills"])
    assert {"calls", "prompt_tokens", "completion_tokens", "flagged", "last_7d"} <= set(
        body["llm"]
    )
    assert {"failed", "stuck"} <= set(body["parse_failures"])


def test_admin_user_directory_and_moderation(admin, seeker):
    listed = client.get("/api/v1/admin/users", headers=admin["headers"])
    assert listed.status_code == 200, listed.text
    payload = listed.json()
    assert payload["total"] >= 2
    assert {"items", "total", "page", "limit", "total_pages"} <= set(payload)
    item = payload["items"][0]
    assert {
        "id",
        "email",
        "role",
        "is_active",
        "is_verified",
        "created_at",
        "profile",
        "companies",
        "applications",
        "last_active_at",
        "hired",
        "open_flags",
    } <= set(item)

    found = client.get(
        "/api/v1/admin/users",
        params={"q": seeker["email"]},
        headers=admin["headers"],
    )
    assert found.status_code == 200
    found_body = found.json()
    assert found_body["total"] == 1
    assert found_body["items"][0]["id"] == seeker["id"]

    seekers = client.get(
        "/api/v1/admin/users",
        params={"role": "job_seeker"},
        headers=admin["headers"],
    )
    assert seekers.status_code == 200
    assert all(row["role"] == "job_seeker" for row in seekers.json()["items"])

    # An admin must not lock themselves out or drop their own privileges.
    self_off = client.patch(
        f"/api/v1/admin/users/{admin['id']}",
        json={"is_active": False},
        headers=admin["headers"],
    )
    assert self_off.status_code == 400
    self_demote = client.patch(
        f"/api/v1/admin/users/{admin['id']}",
        json={"role": "job_seeker"},
        headers=admin["headers"],
    )
    assert self_demote.status_code == 400

    # Other accounts can be deactivated, re-activated and promoted.
    off = client.patch(
        f"/api/v1/admin/users/{seeker['id']}",
        json={"is_active": False},
        headers=admin["headers"],
    )
    assert off.status_code == 200, off.text
    assert off.json()["user"]["is_active"] is False

    inactive = client.get(
        "/api/v1/admin/users",
        params={"is_active": False, "q": seeker["email"]},
        headers=admin["headers"],
    )
    assert inactive.status_code == 200
    assert inactive.json()["total"] == 1

    on = client.patch(
        f"/api/v1/admin/users/{seeker['id']}",
        json={"is_active": True, "role": "employer"},
        headers=admin["headers"],
    )
    assert on.status_code == 200, on.text
    assert on.json()["user"] == {
        "id": seeker["id"],
        "role": "employer",
        "is_active": True,
    }

    missing = client.patch(
        f"/api/v1/admin/users/{uuid4()}",
        json={"is_active": False},
        headers=admin["headers"],
    )
    assert missing.status_code == 404


def test_admin_moderation_employers_and_flags(admin, temp_job):
    """Employer oversight, the flag lifecycle and heuristic scans."""

    employers = client.get(
        "/api/v1/admin/employers",
        params={"q": "Admin Test Co"},
        headers=admin["headers"],
    )
    assert employers.status_code == 200, employers.text
    rows = employers.json()["items"]
    employer = next(row for row in rows if row["id"] == temp_job["company_id"])
    assert {
        "postings",
        "applications",
        "hires",
        "open_flags",
        "flagged_jobs",
        "risk_score",
        "risk_reasons",
    } <= set(employer)

    verified = client.patch(
        f"/api/v1/admin/employers/{temp_job['company_id']}",
        json={"is_verified": True},
        headers=admin["headers"],
    )
    assert verified.status_code == 200, verified.text
    assert verified.json()["company"]["is_verified"] is True

    created = client.post(
        "/api/v1/admin/moderation/flags",
        json={
            "target_type": "job",
            "target_id": temp_job["job_id"],
            "reason": "Asks candidates for a fee",
            "severity": "high",
            "details": "Test evidence",
        },
        headers=admin["headers"],
    )
    assert created.status_code == 201, created.text
    flag = created.json()["flag"]
    assert flag["status"] == "open"
    assert flag["severity"] == "high"
    assert flag["target_label"] == temp_job["title"]
    assert flag["created_by"] == admin["email"]

    try:
        overview = client.get(
            "/api/v1/admin/overview", headers=admin["headers"]
        ).json()
        assert overview["moderation"]["open_flags"] >= 1
        assert overview["moderation"]["high_severity_flags"] >= 1
        assert overview["moderation"]["flagged_jobs"] >= 1

        scan = client.get(
            "/api/v1/admin/moderation/suspicious-jobs",
            params={"limit": 200},
            headers=admin["headers"],
        )
        assert scan.status_code == 200, scan.text
        scanned = {row["id"]: row for row in scan.json()["items"]}
        assert temp_job["job_id"] in scanned
        assert any(
            "moderation flag" in reason
            for reason in scanned[temp_job["job_id"]]["risk_reasons"]
        )

        listing = client.get(
            "/api/v1/admin/moderation/flags", headers=admin["headers"]
        )
        assert listing.status_code == 200
        assert {"open", "resolved", "dismissed"} <= set(listing.json()["counts"])

        resolved = client.patch(
            f"/api/v1/admin/moderation/flags/{flag['id']}",
            json={"status": "resolved", "resolution_note": "Reviewed by admin"},
            headers=admin["headers"],
        )
        assert resolved.status_code == 200, resolved.text
        updated = resolved.json()["flag"]
        assert updated["status"] == "resolved"
        assert updated["resolved_by"] == admin["email"]
        assert updated["resolution_note"] == "Reviewed by admin"

        reopened = client.patch(
            f"/api/v1/admin/moderation/flags/{flag['id']}",
            json={"status": "open"},
            headers=admin["headers"],
        )
        assert reopened.status_code == 200
        assert reopened.json()["flag"]["resolved_at"] is None
    finally:
        with SessionLocal() as db:
            row = db.get(ModerationFlag, UUID(flag["id"]))
            if row is not None:
                db.delete(row)
                db.commit()


def test_admin_job_moderation(admin, temp_job):
    listed = client.get(
        "/api/v1/admin/jobs", params={"q": temp_job["title"]}, headers=admin["headers"]
    )
    assert listed.status_code == 200, listed.text
    payload = listed.json()
    assert payload["total"] == 1
    assert {"items", "total", "page", "limit", "total_pages"} <= set(payload)
    job = payload["items"][0]
    assert job["id"] == temp_job["job_id"]
    assert job["title"] == temp_job["title"]
    assert job["status"] == "draft"
    assert job["company_name"].startswith("Admin Test Co")
    assert {"location", "is_remote", "employment_type", "experience_level",
            "source", "applicants", "created_at"} <= set(job)

    drafts = client.get(
        "/api/v1/admin/jobs", params={"status": "draft"}, headers=admin["headers"]
    )
    assert drafts.status_code == 200
    assert all(row["status"] == "draft" for row in drafts.json()["items"])

    updated = client.patch(
        f"/api/v1/admin/jobs/{temp_job['job_id']}",
        json={"status": "published"},
        headers=admin["headers"],
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["job"]["status"] == "published"

    with SessionLocal() as db:
        stored = db.get(Job, UUID(temp_job["job_id"]))
        assert stored is not None and stored.status == JobStatus.PUBLISHED

    missing = client.patch(
        f"/api/v1/admin/jobs/{uuid4()}",
        json={"status": "published"},
        headers=admin["headers"],
    )
    assert missing.status_code == 404


def test_llm_kill_switch_returns_no_provider(monkeypatch):
    """§22: LLM_ENABLED=false → get_provider() is None (deterministic fallbacks)."""
    from app.services.llm import provider as provider_mod

    real = provider_mod.get_settings()

    class _Killed:
        def __getattr__(self, name):
            if name == "llm_enabled":
                return False
            return getattr(real, name)

    monkeypatch.setattr(provider_mod, "get_settings", lambda: _Killed())
    assert provider_mod.get_provider() is None
