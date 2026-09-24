"""§6 M5 Bradley-Terry elicitation: deterministic fit, Σ=1, tilt direction,
API roundtrip, and the feed adopting the elicited baseline weights.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.db import SessionLocal
from app.main import app
from app.models.job_family import JobFamily
from app.models.ops import SystemConfig
from app.models.profile import Profile
from app.models.user import User
from app.services import elicitation as m5
from app.services.scoring import DEFAULT_WEIGHTS

client = TestClient(app, raise_server_exceptions=False)


def _delete_user(user_id) -> None:
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


def _register() -> dict:
    token = uuid4().hex[:8]
    reg = client.post(
        "/api/v1/auth/register",
        json={
            "email": f"m5_{token}@example.com",
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
    account = _register()
    yield account
    _delete_user(account["id"])


def _choices(side: str) -> list[dict]:
    return [
        {
            "shape_a": pair["a"]["shape"],
            "shape_b": pair["b"]["shape"],
            "chosen": side,
        }
        for pair in m5.PAIRS
    ]


def test_pairs_payload_shape():
    payload = m5.pairs_payload()
    assert len(payload["pairs"]) == 3
    assert len(payload["components"]) == 8
    for pair in payload["pairs"]:
        assert set(pair["a"]["shape"]) == set(DEFAULT_WEIGHTS)
        assert set(pair["b"]["shape"]) == set(DEFAULT_WEIGHTS)
        assert pair["a"]["label"] != pair["b"]["label"]


def test_fit_is_deterministic_and_normalized():
    w1 = m5.fit_weights(_choices("a"))
    w2 = m5.fit_weights(_choices("a"))
    assert w1 == w2, "same choices must yield byte-identical weights"
    assert abs(sum(w1.values()) - 1.0) < 1e-6
    assert all(v > 0 for v in w1.values())
    assert set(w1) == set(DEFAULT_WEIGHTS)


def test_fit_tilts_toward_chosen_shape():
    # Pair 0 option A carries salary 0.95 vs B's 0.30 → choosing A raises salary.
    pick_a = m5.fit_weights(_choices("a"))
    assert pick_a["salary"] > DEFAULT_WEIGHTS["salary"]

    # Choosing B emphasises project/location craft → project rises, salary falls.
    pick_b = m5.fit_weights(_choices("b"))
    assert pick_b["project"] > DEFAULT_WEIGHTS["project"]
    assert pick_b["salary"] < DEFAULT_WEIGHTS["salary"]


def test_onboarding_api_roundtrip(seeker):
    pairs = client.get("/api/v1/onboarding/pairs")
    assert pairs.status_code == 200
    assert len(pairs.json()["pairs"]) == 3

    # one choice per pair required
    bad = client.post(
        "/api/v1/onboarding/complete",
        json={"choices": [{"pair_index": 0, "chosen": "a"}]},
        headers=seeker["headers"],
    )
    assert bad.status_code == 400

    with SessionLocal() as db:
        family = db.scalar(select(JobFamily).limit(1))
        family_name = family.name if family is not None else None

    payload = {
        "choices": [
            {"pair_index": 0, "chosen": "a"},
            {"pair_index": 1, "chosen": "a"},
            {"pair_index": 2, "chosen": "b"},
        ]
    }
    if family_name:
        # unknown family must 404 before anything is stored
        missing = client.post(
            "/api/v1/onboarding/complete",
            json={**payload, "target_family": "Nope Family 123"},
            headers=seeker["headers"],
        )
        assert missing.status_code == 404
        payload["target_family"] = family_name

    done = client.post(
        "/api/v1/onboarding/complete",
        json=payload,
        headers=seeker["headers"],
    )
    assert done.status_code == 200, done.text
    body = done.json()
    weights = {w["component"]: w["weight"] for w in body["weights"]}
    assert abs(sum(weights.values()) - 1.0) < 1e-3
    if family_name:
        assert body["target_family"] == family_name

    # elicited state persisted under m5:{user}
    with SessionLocal() as db:
        stored = m5.load_weights(db, seeker["id"])
        assert stored is not None
        assert abs(sum(stored.values()) - 1.0) < 1e-6
        profile = db.scalar(select(Profile).where(Profile.user_id == UUID(seeker["id"])))
        if family_name:
            assert profile is not None
            assert profile.target_job_family_id is not None

    # Settings bars now adopt the elicited baseline as "global" (§6 M5)
    prefs = client.get("/api/v1/preferences", headers=seeker["headers"])
    assert prefs.status_code == 200
    bars = {b["component"]: b for b in prefs.json()["weights"]}
    assert abs(sum(b["global_weight"] for b in bars.values()) - 1.0) < 1e-3
    assert bars["salary"]["global_weight"] == pytest.approx(
        weights["salary"], abs=0.01
    )
