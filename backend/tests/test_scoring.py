"""Pure unit tests for the deterministic scoring engine (plan §2/§6/§7).

The DESIGN §7 worked example must produce EXACTLY 74.0 — this golden vector
is authoritative (the c_lo/c_hi semantic piecewise may refit at eval time;
this number must not drift).  No DB required.

Runs with or without pytest:
    cd backend && python tests/test_scoring.py
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend/
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://x:x@localhost:55432/x")
os.environ.setdefault("EMBEDDING_BACKEND", "hashing")

from app.models.enums import ExperienceLevel, ProficiencyLevel
from app.services.scoring import (
    DEFAULT_WEIGHTS,
    NEUTRAL_EDUCATION,
    NEUTRAL_EXPERIENCE,
    NEUTRAL_SALARY,
    NEUTRAL_SKILLS,
    ComponentInputs,
    JobSkillReq,
    combine,
    education_match,
    experience_match,
    score_pair,
    semantic_similarity,
    skill_match,
)

# DESIGN §7 worked example (plan §2 reproduced) — golden, exact
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


def test_weights_sum_to_one():
    assert abs(sum(DEFAULT_WEIGHTS.values()) - 1.0) < 1e-9
    assert set(DEFAULT_WEIGHTS) == set(GOLDEN)


def test_golden_example_is_exactly_74():
    final, contributions = combine(GOLDEN)
    assert final == 74.0, f"golden worked example must be 74.0, got {final}"
    assert abs(sum(contributions.values()) - final) <= 0.15
    # plan §7 contribution table, verbatim
    assert contributions["semantic"] == 21.0
    assert contributions["skill"] == 17.0
    assert contributions["experience"] == 12.75
    assert contributions["education"] == 10.0
    assert contributions["project"] == 2.5
    assert contributions["location"] == 4.0
    assert contributions["salary"] == 3.0
    assert contributions["interest"] == 3.75


def test_combine_fills_missing_with_neutrals():
    final, contributions = combine({"semantic": 70.0})
    # partially-specified input must not crash or skew: rest = neutral priors
    assert set(contributions) == set(DEFAULT_WEIGHTS)
    assert contributions["semantic"] == 21.0
    assert contributions["salary"] == round(DEFAULT_WEIGHTS["salary"] * NEUTRAL_SALARY, 4)
    assert contributions["education"] == round(DEFAULT_WEIGHTS["education"] * NEUTRAL_EDUCATION, 4)
    assert contributions["skill"] == round(DEFAULT_WEIGHTS["skill"] * NEUTRAL_SKILLS, 4)
    assert 0.0 <= final <= 100.0


def test_semantic_piecewise_window_and_clamps():
    assert semantic_similarity(None) == NEUTRAL_EXPERIENCE  # embeddings unavailable
    assert semantic_similarity(0.25) == 0.0                 # c_lo
    assert semantic_similarity(0.50) == 50.0                # midpoint
    assert semantic_similarity(0.75) == 100.0               # c_hi
    assert semantic_similarity(1.0) == 100.0                # clamped
    assert semantic_similarity(-1.0) == 0.0                 # clamped


def test_experience_bands():
    assert experience_match(3.0, ExperienceLevel.MID) == 100.0     # in band [2,5]
    assert experience_match(None, ExperienceLevel.MID) == NEUTRAL_EXPERIENCE
    assert experience_match(3.0, ExperienceLevel.SENIOR) == 50.0    # 100-2*25
    assert experience_match(0.0, ExperienceLevel.SENIOR) == 20.0    # underqual floor
    assert experience_match(15.0, ExperienceLevel.MID) == 60.0      # overqual floor


def test_education_ranks_and_priors():
    assert education_match(None, None) == NEUTRAL_EDUCATION        # no stated bar
    assert education_match("bachelor", None) == NEUTRAL_EDUCATION
    assert education_match("bachelor", "master") == 75.0           # one-rank gap
    assert education_match("master", "bachelor") == 100.0          # overqualified OK
    assert education_match(None, "bachelor") == 60.0               # unknown seeker
    # field mismatch only penalises when a field is required
    assert education_match("bachelor", "bachelor", "arts", "computer science") == 60.0


def test_skill_neutral_when_job_lists_none():
    detail = skill_match(ComponentInputs())
    assert detail.score == NEUTRAL_SKILLS
    assert detail.reasons == ["Job has no strict skill prerequisites."]


def test_skill_strong_partial_and_missing_classes():
    inputs = ComponentInputs(
        seeker_skills={
            "python": (ProficiencyLevel.ADVANCED, 4.0),   # strong evidence
            "docker": (ProficiencyLevel.BEGINNER, 0.5),    # <2y beginner -> partial
        },
        job_skills=[
            JobSkillReq(name="Python", is_required=True, importance_weight=1.0),
            JobSkillReq(name="Docker", is_required=True, importance_weight=1.0),
            JobSkillReq(name="Kubernetes", is_required=True, importance_weight=1.0),
        ],
    )
    detail = skill_match(inputs)
    # required w_eff = 1.6 each; gains = 1.6*1.0 + 1.6*0.6 = 2.56 of 4.8
    assert detail.score == 53.3, detail.score
    assert detail.matched == ["Python", "Docker"]
    assert detail.partial == ["Docker"]
    assert detail.missing_required == ["Kubernetes"]
    assert detail.reasons


def test_skill_transfer_credit_is_capped_at_70_percent():
    inputs = ComponentInputs(
        seeker_skills={"tensorflow": (ProficiencyLevel.ADVANCED, 3.0)},
        job_skills=[JobSkillReq(name="PyTorch", is_required=True, importance_weight=1.0)],
        transfer_similarities={"pytorch": 0.85},
    )
    detail = skill_match(inputs)
    # credit = 0.7 * min(1, 0.85) = 0.595 -> 100 * 1.6*0.595 / 1.6
    assert detail.score == 59.5, detail.score
    assert detail.transferable == ["PyTorch"]
    assert detail.matched == []
    # even a perfect transfer never exceeds the 0.7 floor credit
    inputs.transfer_similarities = {"pytorch": 1.0}
    assert skill_match(inputs).score == 70.0


def test_score_pair_bounds_and_consistency():
    inputs = ComponentInputs(
        semantic_cosine=0.6,
        seeker_skills={"python": (ProficiencyLevel.ADVANCED, 4.0)},
        job_skills=[
            JobSkillReq(name="Python", is_required=True),
            JobSkillReq(name="React", is_required=False),
        ],
        years_of_experience=3.5,
        job_level=ExperienceLevel.MID,
        seeker_location="Pune, India",
        job_location="Pune, India",
        seeker_target_family="Backend Engineering",
        job_family="Backend Engineering",
    )
    result = score_pair(inputs)
    assert set(result.components) == set(DEFAULT_WEIGHTS)
    for name, value in result.components.items():
        assert 0.0 <= value <= 100.0, f"{name} out of range: {value}"
    assert abs(sum(result.contributions.values()) - result.final) <= 0.15
    assert result.components["semantic"] == 70.0  # (0.60-0.25)/0.50 window
    assert result.skill_detail.matched == ["Python"]
    # preferred (non-required) skill absent is NOT a gap
    assert "React" not in result.skill_detail.missing_required
    assert result.final > 0.0


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
