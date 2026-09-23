"""MMR diversity re-ranking + exploration slot (plan §4/§16).

Deterministic: no randomness anywhere.  Two mechanisms:

1. Maximal Marginal Relevance — trades relevance against redundancy using
   embedding cosine so the feed isn't 10 near-identical postings.
2. Family cap — at most `family_cap` jobs from the same job family in the
   top `family_cap_window` slots (default: ≤3 per family in the top 10),
   relaxed only if the candidate pool would otherwise under-fill.

Exploration is applied by the caller (recommender) with a deterministic
seed (user id + date), logging propensity on the served Recommendation row.
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import date
from hashlib import sha256
from typing import Sequence

import numpy as np


def pairwise_cosine(vectors: np.ndarray) -> np.ndarray:
    """(n, d) L2-normalised or not -> (n, n) cosine matrix, diagonal 1."""
    if vectors.size == 0:
        return np.zeros((0, 0), dtype=np.float32)
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    normed = vectors / norms
    return np.clip(normed @ normed.T, -1.0, 1.0)


def mmr_order(
    relevance: Sequence[float],
    vectors: np.ndarray | None,
    limit: int,
    lamb: float = 0.7,
) -> list[int]:
    """Return indices in MMR-selected order.

    relevance: scores already in candidate order.
    vectors: (n, 384) embeddings; None → pure relevance order.
    lamb: 1.0 = pure relevance, 0.0 = pure diversity.
    """
    n = len(relevance)
    if n == 0:
        return []
    rel = np.asarray(relevance, dtype=np.float64)
    # normalise relevance to [0,1] so lambda is meaningful across scales
    rmax, rmin = float(rel.max()), float(rel.min())
    rel_n = (rel - rmin) / (rmax - rmin) if rmax > rmin else np.ones_like(rel)

    sim = pairwise_cosine(vectors) if vectors is not None else np.zeros((n, n))

    remaining = set(range(n))
    order: list[int] = []
    picked: list[int] = []
    while remaining and len(order) < min(limit, n):
        best_idx = -1
        best_val = -math.inf
        for idx in sorted(remaining):  # deterministic tie-break: input order
            redundancy = max((float(sim[idx][p]) for p in picked), default=0.0)
            # shift cosine from [-1,1] to [0,1] so it can't reward dissimilarity oddly
            redundancy = (redundancy + 1.0) / 2.0
            val = lamb * float(rel_n[idx]) - (1.0 - lamb) * redundancy
            if val > best_val:
                best_val, best_idx = val, idx
        if best_idx < 0:
            break
        order.append(best_idx)
        picked.append(best_idx)
        remaining.discard(best_idx)
    # MMR prefix honours `limit`; leftovers (when limit < n) appended in input
    # order so callers always get a complete pool to slice from
    order.extend(sorted(remaining))
    return order


def apply_family_cap(
    candidate_indices: list[int],
    families: Sequence[str | None],
    limit: int,
    family_cap: int = 3,
    cap_window: int = 10,
) -> list[int]:
    """Greedy pass enforcing ≤ family_cap per family within the first cap_window slots.

    The cap applies only inside the window (plan §4: "≤3 per job family in the
    top 10"); slots beyond the window are unrestricted.  If respecting the cap
    would leave a window slot empty, the constraint is relaxed for that slot
    rather than returning fewer results.
    """
    window = min(cap_window, limit)
    selected: list[int] = []
    counts: dict[str, int] = defaultdict(int)
    remaining = list(candidate_indices)

    for _slot in range(window):
        if not remaining:
            break
        picked = None
        for idx in remaining:
            fam = families[idx] or f"__none_{idx}"
            if counts[fam] < family_cap:
                picked = idx
                break
        if picked is None:
            picked = remaining[0]  # relax: pool is family-saturated
        remaining.remove(picked)
        selected.append(picked)
        counts[families[picked] or f"__none_{picked}"] += 1

    selected.extend(remaining)  # beyond window: unrestricted
    return selected


def exploration_should_apply(user_id: str, on: date | None = None, rate: float = 1 / 6) -> bool:
    """Deterministic 1-in-N exploration decision per (user, day).

    Hash(user_id + date) → [0,1); applies when < rate.  Same user gets the
    same decision all day (stable feed), different users differ (~rate share).
    """
    on = on or date.today()
    digest = sha256(f"{user_id}:{on.isoformat()}".encode()).digest()
    value = int.from_bytes(digest[:8], "big") / float(1 << 64)
    return value < rate


def exploration_propensity(rate: float = 1 / 6) -> float:
    """Logged inverse-propensity weight for exploration slots (plan §16)."""
    return round(rate, 4)
