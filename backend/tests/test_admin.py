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
from app.models.enums import UserRole
from app.models.ops import SystemConfig
from app.models.profile import Profile
from app.models.skill import ProfileSkill, Skill
from app.models.skill_graph import SkillAlias
from app.models.user import User
from app.services.scoring import DEFAULT_WEIGHTS

client = TestClient(app, raise_server_exceptions=False)

ADMIN_ROUTES = [
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
    reg = client.post(
        "/api/v1/auth/register",
        json={
            "email": f"{prefix}_{token}@example.com",
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
