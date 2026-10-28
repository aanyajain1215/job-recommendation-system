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


# ---------------------------------------------------------------------------
# Adaptive (multi-option, Plackett-Luce) flow
# ---------------------------------------------------------------------------

def _fit_rows(answers: list[dict]) -> list[dict]:
    """Lightweight {index, chosen} answers → full fit rows."""
    rows = []
    for a in answers:
        q = m5.BANK_BY_INDEX[a["index"]]
        keys = [k for k in ("a", "b", "c") if k in q]
        rows.append(
            {"shapes": [q[k]["shape"] for k in keys], "chosen": keys.index(a["chosen"])}
        )
    return rows


def test_bank_is_well_formed():
    assert len(m5.QUESTION_BANK) == m5.ADAPTIVE_POOL
    assert len({q["index"] for q in m5.QUESTION_BANK}) == m5.ADAPTIVE_POOL
    for q in m5.QUESTION_BANK:
        # every question offers three options, each covering all 8 axes
        for k in ("a", "b", "c"):
            assert set(q[k]["shape"]) == set(DEFAULT_WEIGHTS)
            assert all(0.0 <= v <= 1.0 for v in q[k]["shape"].values())
        labels = {q[k]["label"] for k in ("a", "b", "c")}
        assert len(labels) == 3, "options within a question must be distinct"


def test_multioption_fit_is_deterministic_and_normalized():
    answers = [
        {"index": q["index"], "chosen": "a"} for q in m5.QUESTION_BANK[:3]
    ]
    rows = _fit_rows(answers)
    w1 = m5.fit_weights_multioption(rows)
    w2 = m5.fit_weights_multioption(rows)
    assert w1 == w2, "same answers must yield identical weights"
    assert abs(sum(w1.values()) - 1.0) < 1e-6
    assert all(v > 0 for v in w1.values())
    assert set(w1) == set(DEFAULT_WEIGHTS)


def test_multioption_reduces_to_binary_for_two_options():
    # A two-option question answered 'a' must tilt the same way as the legacy
    # Bradley-Terry fit on the same shapes (both are the logistic model).
    pair = m5.PAIRS[0]
    legacy = m5.fit_weights(
        [{"shape_a": pair["a"]["shape"], "shape_b": pair["b"]["shape"], "chosen": "a"}]
    )
    multi = m5.fit_weights_multioption(
        [{"shapes": [pair["a"]["shape"], pair["b"]["shape"]], "chosen": 0}]
    )
    # directions agree (salary rises under both); exact values differ only by
    # the shared regulariser's interaction with the option count.
    assert legacy["salary"] > DEFAULT_WEIGHTS["salary"]
    assert multi["salary"] > DEFAULT_WEIGHTS["salary"]
    assert multi["project"] < DEFAULT_WEIGHTS["project"]


def test_select_next_question_adapts_and_never_repeats():
    first = m5.select_next_question([])
    assert first is not None and first["index"] in m5.BANK_BY_INDEX

    asked = [{"index": first["index"], "chosen": "a"}]
    second = m5.select_next_question(asked)
    assert second["index"] != first["index"], "must not re-ask the same question"

    # deterministic: same answers → same next question
    assert m5.select_next_question(asked)["index"] == second["index"]

    # exhausting the bank returns None (no crash)
    all_asked = [{"index": q["index"], "chosen": "a"} for q in m5.QUESTION_BANK]
    assert m5.select_next_question(all_asked) is None


def test_adaptive_fit_tilts_toward_chosen_shape():
    # Always pick the option with the highest salary → salary must rise.
    answers, q = [], m5.select_next_question([])
    for _ in range(4):
        keys = [k for k in ("a", "b", "c") if k in q]
        best = max(keys, key=lambda k: q[k]["shape"]["salary"])
        answers.append({"index": q["index"], "chosen": best})
        q = m5.select_next_question(answers)
    w = m5.fit_weights_multioption(_fit_rows(answers))
    assert w["salary"] > DEFAULT_WEIGHTS["salary"]


def test_flow_and_next_endpoints(seeker):
    flow = client.get("/api/v1/onboarding/flow")
    assert flow.status_code == 200
    body = flow.json()
    assert body["question"] is not None
    assert len(body["preview_weights"]) == 8
    assert body["min_questions"] == m5.MIN_QUESTIONS

    # POST /next adapts: answering the first question yields a different one
    idx = body["question"]["index"]
    nxt = client.post(
        "/api/v1/onboarding/next", json={"answers": [{"index": idx, "chosen": "a"}]}
    )
    assert nxt.status_code == 200
    assert nxt.json()["question"]["index"] != idx
    assert nxt.json()["answered"] == 1


def test_complete_adaptive_roundtrip(seeker):
    answers = [{"index": q["index"], "chosen": "a"} for q in m5.QUESTION_BANK[:3]]

    # too few answers → 400
    short = client.post(
        "/api/v1/onboarding/complete",
        json={"answers": answers[:2]},
        headers=seeker["headers"],
    )
    assert short.status_code == 400

    # unknown question index → 400
    bad = client.post(
        "/api/v1/onboarding/complete",
        json={"answers": answers + [{"index": 999, "chosen": "a"}]},
        headers=seeker["headers"],
    )
    assert bad.status_code == 400

    done = client.post(
        "/api/v1/onboarding/complete",
        json={"answers": answers},
        headers=seeker["headers"],
    )
    assert done.status_code == 200, done.text
    weights = {w["component"]: w["weight"] for w in done.json()["weights"]}
    assert abs(sum(weights.values()) - 1.0) < 1e-3

    # persisted under m5:{user} with the adaptive origin
    with SessionLocal() as db:
        raw = m5.load_raw(db, seeker["id"])
        assert raw is not None
        assert raw["origin"] == "m5_adaptive_plackett_luce"
        assert raw["n_choices"] == 3
        assert m5.load_weights(db, seeker["id"]) is not None

    # the feed's base weights now adopt the elicited vector
    prefs = client.get("/api/v1/preferences", headers=seeker["headers"])
    assert prefs.status_code == 200
    bars = {b["component"]: b for b in prefs.json()["weights"]}
    assert bars["salary"]["global_weight"] == pytest.approx(
        weights["salary"], abs=0.01
    )
