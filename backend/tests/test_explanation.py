"""Unit tests for the §12 explanation contract + readiness bands (plan §12).

Numbers flow verbatim from the deterministic scorer into the contract; the
validator proves no layer can drift.  The LLM may polish `summary` only in
Phase 2 — never the numbers.  No DB required.

Runs with or without pytest:
    cd backend && python tests/test_explanation.py
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend/
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://x:x@localhost:55432/x")
os.environ.setdefault("EMBEDDING_BACKEND", "hashing")

from app.services.explanation import (
    build_explanation,
    readiness_from_score,
    validate_explanation,
)
from app.services.scoring import ScoreResult, SkillMatchDetail, combine

# DESIGN §7 worked example — golden components, final = 74.0
GOLDEN = {
    "semantic": 70.0,
    "skill": 68.0,
    "experience": 85.0,
    "education": 100.0,
    "project": 50.0,
    "location": 80.0,
    "salary": 60.0,
    "interest": 75.0,
}


def _result() -> ScoreResult:
    final, contributions = combine(GOLDEN)
    return ScoreResult(
        final=final,
        components=dict(GOLDEN),
        contributions=contributions,
        skill_detail=SkillMatchDetail(
            score=68.0,
            matched=["Python", "FastAPI"],
            missing_required=["Kubernetes"],
            reasons=["Matches 2 relevant skills: Python, FastAPI"],
        ),
    )


def test_contract_numbers_are_verbatim_and_valid():
    result = _result()
    contract = build_explanation(
        "ML Engineer", "Acme Labs", result, family="Data Science"
    )
    assert contract.components == result.components        # verbatim, no recompute
    assert contract.contributions == result.contributions  # verbatim
    assert validate_explanation(contract, result.final) == []
    assert "74.0%" in contract.summary
    assert "strong" in contract.summary                   # band for 74 (70..84)
    assert "Data Science" in contract.summary
    assert contract.strengths                             # matched skills + components
    assert contract.concerns                              # missing required
    assert "Kubernetes" in contract.recommended_action    # first gap drives action
    assert contract.delta_note is None                    # deterministic in Phase 1


def test_validator_flags_out_of_range_component():
    result = _result()
    contract = build_explanation("ML Engineer", None, result)
    contract.components["skill"] = 150.0
    problems = validate_explanation(contract, result.final)
    assert any("outside [0,100]" in p for p in problems)


def test_validator_flags_contribution_sum_drift():
    result = _result()
    contract = build_explanation("ML Engineer", None, result)
    contract.contributions["skill"] += 5.0
    problems = validate_explanation(contract, result.final)
    assert any("!=" in p for p in problems)


def test_validator_flags_key_mismatch_and_empty_action():
    result = _result()

    c1 = build_explanation("ML Engineer", None, result)
    del c1.contributions["interest"]
    assert any("keys" in p for p in validate_explanation(c1, result.final))

    c2 = build_explanation("ML Engineer", None, result)
    c2.recommended_action = ""
    assert any("recommended_action" in p for p in validate_explanation(c2, result.final))


def test_display_score_override_keeps_numbers_verbatim():
    # ltr_blend may show a different score; components must stay deterministic
    result = _result()
    contract = build_explanation("ML Engineer", "Acme", result, display_score=68.0)
    assert "68.0%" in contract.summary
    assert contract.components == result.components
    assert contract.contributions == result.contributions
    assert validate_explanation(contract, result.final) == []


def test_readiness_bands_phase1_mapping():
    # Fallback contract (no calibrator artifact / flag off): exact Phase-1
    # raw mapping — low < 0.50 <= medium < 0.75 <= high.  Patched manually
    # (no fixtures) so the direct-run path below keeps working.
    import app.services.calibration as calibration

    original = calibration.predict_positive
    calibration.predict_positive = lambda score: None
    try:
        assert readiness_from_score(49.0) == {"value": 0.49, "band": "low"}
        assert readiness_from_score(50.0) == {"value": 0.5, "band": "medium"}
        assert readiness_from_score(74.0) == {"value": 0.74, "band": "medium"}
        assert readiness_from_score(75.0) == {"value": 0.75, "band": "high"}
        assert readiness_from_score(150.0) == {"value": 1.0, "band": "high"}   # clamped
        assert readiness_from_score(-10.0) == {"value": 0.0, "band": "low"}    # clamped
    finally:
        calibration.predict_positive = original


def test_readiness_bands_calibrated_path():
    # M3 calibrated path (plan §6): value = P(positive outcome), bands from
    # settings (default low < 0.60 <= medium < 0.80 <= high).  Fake monotone
    # calibrator: P = clamp((score - 30) / 80).
    import app.services.calibration as calibration

    original = calibration.predict_positive
    calibration.predict_positive = lambda s: max(0.0, min(1.0, (s - 30.0) / 80.0))
    try:
        assert readiness_from_score(62.0) == {"value": 0.4, "band": "low"}     # P=0.40
        assert readiness_from_score(78.0) == {"value": 0.6, "band": "medium"}  # P=0.60
        assert readiness_from_score(94.0) == {"value": 0.8, "band": "high"}    # P=0.80
        assert readiness_from_score(150.0) == {"value": 1.0, "band": "high"}
        assert readiness_from_score(-10.0) == {"value": 0.0, "band": "low"}
        # isotonic calibrators are monotone → roadmap/simulator orderings hold
        values = [readiness_from_score(s)["value"] for s in range(0, 101, 5)]
        assert all(b >= a for a, b in zip(values, values[1:]))
    finally:
        calibration.predict_positive = original


# ---------------------------------------------------------------------------
# Direct-run fallback (host/container may not have pytest)
# ---------------------------------------------------------------------------

def _run_all() -> int:
    failures = 0
    for name in sorted(list(globals())):
        fn = globals()[name]
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except Exception as exc:  # noqa: BLE001
                failures += 1
                print(f"FAIL {name}: {type(exc).__name__}: {exc}")
    print("ALL TESTS PASSED" if not failures else f"{failures} TEST(S) FAILED")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(_run_all())
