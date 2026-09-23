"""Pure unit tests for the skill-name normalizer cascade (plan §20).

Cascade order: exact -> alias -> fuzzy (rapidfuzz >= 92) -> propose new.
Original input is always preserved for evidence.  No DB required.

Runs with or without pytest:
    cd backend && python tests/test_normalizer.py
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend/
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://x:x@localhost:55432/x")
os.environ.setdefault("EMBEDDING_BACKEND", "hashing")

from app.services.skill_normalizer import FUZZY_THRESHOLD, SkillNormalizer


def _norm() -> SkillNormalizer:
    return SkillNormalizer(
        ["React", "Node.js", "PostgreSQL", "Kubernetes"],
        [("reactjs", "React"), ("postgres", "PostgreSQL")],
    )


def test_exact_match_is_case_and_whitespace_insensitive():
    result = _norm().normalize("  ReAcT ")
    assert result.matched and result.method == "exact"
    assert result.canonical == "React"
    assert result.score == 100.0


def test_alias_match_resolves_to_canonical():
    result = _norm().normalize("ReactJS")
    assert result.matched and result.method == "alias"
    assert result.canonical == "React"


def test_alias_dotted_variant():
    result = _norm().normalize("postgres")
    assert result.matched and result.method == "alias"
    assert result.canonical == "PostgreSQL"


def test_fuzzy_match_above_threshold():
    # indel ratio: 2*9/(9+10) = 94.7 >= 92 -> canonical Kubernetes
    result = _norm().normalize("kubernete")
    assert result.matched and result.method == "fuzzy"
    assert result.canonical == "Kubernetes"
    assert result.score >= FUZZY_THRESHOLD


def test_below_threshold_proposes_new():
    result = _norm().normalize("zzzzzzq")
    assert not result.matched and result.method == "new"
    assert result.canonical == "zzzzzzq"


def test_empty_input_is_new_not_crash():
    result = _norm().normalize("   ")
    assert not result.matched and result.method == "new"
    assert result.canonical == ""


def test_original_preserved_for_evidence():
    result = _norm().normalize("  ReactJS ")
    assert result.original == "  ReactJS "
    assert result.canonical == "React"


def test_real_seed_yaml_resolves_design_aliases():
    # DESIGN acceptance (§23 M1): aliases resolve React.js = React
    yaml_norm = SkillNormalizer.from_yaml()
    r1 = yaml_norm.normalize("React.js")
    assert r1.matched and r1.canonical == "React"
    r2 = yaml_norm.normalize("k8s")
    assert r2.matched and r2.canonical == "Kubernetes"
    r3 = yaml_norm.normalize("kubernetes")
    assert r3.matched and r3.canonical == "Kubernetes"


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
