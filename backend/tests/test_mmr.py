"""Unit tests for MMR diversity, per-family caps, and the exploration slot
(plan §4/§16).  Everything here is deterministic — no randomness anywhere;
the exploration draw is a stable sha256 over (user_id, date).

Runs with or without pytest:
    cd backend && python tests/test_mmr.py
"""

import os
import sys
from collections import Counter
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend/
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://x:x@localhost:55432/x")
os.environ.setdefault("EMBEDDING_BACKEND", "hashing")

import numpy as np

from app.services.mmr import (
    apply_family_cap,
    exploration_propensity,
    exploration_should_apply,
    mmr_order,
    pairwise_cosine,
)


def test_pairwise_cosine_matrix_shape_and_diagonal():
    vecs = np.eye(4, 8, dtype=np.float32)
    sim = pairwise_cosine(vecs)
    assert sim.shape == (4, 4)
    assert np.allclose(np.diag(sim), 1.0)
    assert np.allclose(sim, sim.T)
    empty = pairwise_cosine(np.zeros((0, 3), dtype=np.float32))
    assert empty.shape == (0, 0)


def test_mmr_is_deterministic_permutation():
    rel = [80.0, 79.0, 79.5, 40.0, 81.0]
    vecs = np.eye(5, 384, dtype=np.float32)
    order = mmr_order(rel, vecs, 5, 0.7)
    assert order == mmr_order(rel, vecs, 5, 0.7)   # same input -> same output
    assert sorted(order) == [0, 1, 2, 3, 4]        # every candidate exactly once
    assert order[0] == 4                           # top relevance picked first


def test_mmr_lambda_one_is_pure_relevance():
    assert mmr_order([55.0, 91.0, 70.0], None, 3, 1.0) == [1, 2, 0]


def test_mmr_without_vectors_is_relevance_order():
    assert mmr_order([10.0, 90.0, 50.0], None, 3, 0.7) == [1, 2, 0]


def test_mmr_limit_controls_selected_prefix():
    order = mmr_order([5.0, 9.0, 7.0, 8.0], None, 2, 1.0)
    assert order[:2] == [1, 3]                # MMR-selected prefix honours `limit`
    assert sorted(order) == [0, 1, 2, 3]      # full pool returned; callers slice [:limit]


def test_mmr_prefers_diverse_near_tie():
    # items 0 and 1 are identical vectors; item 2 has near-equal relevance
    # but a different embedding — MMR must prefer the dissimilar one.
    rel = [90.0, 90.0, 89.8, 89.0]
    vecs = np.array(
        [[1.0, 0.0], [1.0, 0.0], [0.0, 1.0], [0.0, 1.0]], dtype=np.float32
    )
    order = mmr_order(rel, vecs, 4, 0.7)
    assert order[0] == 0
    assert order[1] == 2                           # diversity beat the twin
    assert sorted(order) == [0, 1, 2, 3]


def test_family_cap_enforced_in_top_window():
    # plan §4: ≤3 per family in the top 10; skipped members wait their turn
    families = ["A", "A", "A", "A", "B", "B", "B", "B", "C", "C", "C", "D"]
    out = apply_family_cap(
        list(range(12)), families, limit=12, family_cap=3, cap_window=10
    )
    assert sorted(out) == list(range(12))          # permutation, nothing dropped
    window = out[:10]
    assert window == [0, 1, 2, 4, 5, 6, 8, 9, 10, 11]
    assert window == sorted(window)                # relative order preserved
    counts = Counter(families[i] for i in window)
    assert max(counts.values()) <= 3
    assert out[10:] == [3, 7]                      # beyond the window: unrestricted


def test_family_cap_relaxes_when_pool_is_saturated():
    # only two families for ten slots: under-fill must never happen —
    # the cap holds while supply lasts, then relaxes rather than returning fewer
    families = ["A"] * 5 + ["B"] * 5
    out = apply_family_cap(
        list(range(10)), families, limit=10, family_cap=3, cap_window=10
    )
    assert sorted(out) == list(range(10))          # all slots filled
    assert out[:6] == [0, 1, 2, 5, 6, 7]           # cap respected first


def test_family_cap_ignores_unknown_families():
    families = [None] * 12
    out = apply_family_cap(list(range(12)), families, limit=12)
    assert out == list(range(12))                  # None never groups together


def test_exploration_is_deterministic_per_user_day():
    day = date(2026, 9, 24)
    first = exploration_should_apply("user-42", on=day, rate=1 / 6)
    assert first == exploration_should_apply("user-42", on=day, rate=1 / 6)
    assert exploration_should_apply("user-42", on=day, rate=0.0) is False
    assert exploration_should_apply("user-42", on=day, rate=1.0) is True


def test_exploration_seed_includes_the_day():
    base = exploration_should_apply("user-42", on=date(2026, 9, 24), rate=0.5)
    flips = any(
        exploration_should_apply("user-42", on=date(2026, 9, d), rate=0.5) != base
        for d in range(1, 29)
    )
    assert flips  # same user, different day -> different stable draw


def test_exploration_cohort_split_is_sane():
    day = date(2026, 9, 24)
    flags = [exploration_should_apply(f"u{i}", on=day, rate=0.5) for i in range(60)]
    assert 5 < sum(flags) < 55                     # not all-or-nothing


def test_propensity_logging_value():
    assert exploration_propensity(0.5) == 0.5
    assert exploration_propensity() == round(1 / 6, 4)


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
