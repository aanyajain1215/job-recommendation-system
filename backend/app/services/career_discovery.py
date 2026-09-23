"""Alternative Career Discovery (plan §11).

Affinity of the seeker's profile to every job family, using the SAME
four-class rule as the gap engine (`gap_engine.classify` — one code path):

    overlap = Σ over family core skills:
        STRONG  → settings weight (1.0)
        PARTIAL → settings weight (0.6)
        TRANSFERABLE → transfer weight (0.7) × transfer similarity
        MISSING → 0
    overlap_norm = overlap / |core skills|            ∈ [0, 1]
    semantic     = profile↔family-centroid cosine, scaled through the
                   scoring engine's §6 window to [0, 1]
    affinity     = 100 × (0.7·overlap_norm + 0.3·semantic)   ∈ [0, 100]

Suggestions are families with affinity ≥ τ (settings, default 55.0),
excluding the seeker's current target family.  Every suggestion carries an
evidence explanation: top-4 overlapping skills, transfer count, and the
nearest family-graph edge.  Presets are rendered through this exact same
math — never a second formula.
"""

from __future__ import annotations

from typing import Any, Sequence

import numpy as np

from app.core.config import get_settings
from app.models.enums import ProficiencyLevel
from app.services.gap_engine import PARTIAL, STRONG, TRANSFERABLE, classify
from app.services.scoring import SEMANTIC_C_HIGH, SEMANTIC_C_LOW
from app.services.skill_graph import SkillGraph, transfer_similarity


def _scale_semantic(cosine: float | None) -> float:
    """Cosine → [0,1] through the plan §6 piecewise window (shared constants)."""
    if cosine is None:
        return 0.5  # neutral prior when embeddings are unavailable
    scaled = (cosine - SEMANTIC_C_LOW) / (SEMANTIC_C_HIGH - SEMANTIC_C_LOW)
    return max(0.0, min(1.0, scaled))


def _centroid(vectors: Sequence[list[float]]) -> np.ndarray | None:
    usable = [np.asarray(v, dtype=np.float32) for v in vectors if v is not None and len(v)]
    if not usable:
        return None
    return np.mean(np.stack(usable), axis=0)


def _cosine(a: np.ndarray | None, b: np.ndarray | None) -> float | None:
    if a is None or b is None:
        return None
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom <= 0:
        return None
    return float(np.dot(a, b) / denom)


def nearest_family_edge(
    family: Any,
    target: Any | None,
    families_by_id: dict[Any, Any],
) -> dict[str, Any] | None:
    """Nearest graph edge between the current target family and a candidate
    (plan §11 explanation contract: family-tree relation, deterministic)."""
    if target is None or family.id == getattr(target, "id", None):
        return None
    if family.parent_id == getattr(target, "id", None):
        return {"from": target.name, "to": family.name, "relation": "direct child"}
    if getattr(target, "parent_id", None) == family.id:
        return {"from": target.name, "to": family.name, "relation": "direct parent"}
    if (
        family.parent_id is not None
        and family.parent_id == getattr(target, "parent_id", None)
    ):
        parent = families_by_id.get(family.parent_id)
        return {
            "from": target.name,
            "to": family.name,
            "relation": f"sibling (shared parent: {parent.name if parent else '?'})",
        }
    return {"from": target.name, "to": family.name, "relation": "distant"}


def affinity_for_family(
    family: Any,
    seeker_skills: dict[str, tuple[ProficiencyLevel | None, float | None]],
    graph: SkillGraph,
    profile_embedding: Any,
    skill_embeddings: dict[str, Any],
    target: Any | None,
    families_by_id: dict[Any, Any],
) -> dict[str, Any] | None:
    """Affinity + evidence explanation for one family (plan §11).

    Returns None when the family declares no core skills (nothing to measure
    against — honest absence rather than an invented number).
    """
    settings = get_settings()
    core = [str(s) for s in (family.core_skills or []) if str(s).strip()]
    if not core:
        return None

    possessed = set(seeker_skills)
    threshold = settings.transfer_similarity_threshold

    overlap = 0.0
    overlapping: list[tuple[str, str]] = []  # (name, status)
    transfer_count = 0
    for name in core:
        key = name.lower().strip()
        sim = transfer_similarity(graph, possessed, name)
        transfers = {key: sim} if sim is not None else {}
        status, evidence = classify(
            key, seeker_skills, transfers, graph, threshold
        )
        if status == STRONG:
            overlap += settings.discovery_weight_strong
            overlapping.append((name, status))
        elif status == PARTIAL:
            overlap += settings.discovery_weight_partial
            overlapping.append((name, status))
        elif status == TRANSFERABLE:
            cos = float(evidence.get("transfer_similarity", threshold))
            overlap += settings.discovery_weight_transfer * cos
            overlapping.append((name, status))
            transfer_count += 1

    overlap_norm = max(0.0, min(1.0, overlap / len(core)))

    vecs = [skill_embeddings[n.lower().strip()] for n in core if n.lower().strip() in skill_embeddings]
    semantic = _scale_semantic(_cosine(_centroid(vecs), _to_np(profile_embedding)))

    w_sem = settings.discovery_weight_semantic
    affinity = round(
        100.0 * ((1.0 - w_sem) * overlap_norm + w_sem * semantic), 2
    )

    # Explanation: top-4 overlaps (strong first, then partial, then transfer)
    priority = {STRONG: 0, PARTIAL: 1, TRANSFERABLE: 2}
    top = [
        name
        for name, status in sorted(
            overlapping, key=lambda t: (priority.get(t[1], 9), t[0].lower())
        )[:4]
    ]

    return {
        "family_id": str(family.id),
        "family": family.name,
        "affinity": affinity,
        "overlap": round(overlap_norm, 3),
        "semantic": round(semantic, 3),
        "core_skill_count": len(core),
        "matched_count": len(overlapping),
        "transfer_count": transfer_count,
        "explanation": {
            "top_skills": top,
            "transfer_count": transfer_count,
            "nearest_edge": nearest_family_edge(family, target, families_by_id),
            "note": (
                f"{len(overlapping)} of {len(core)} core skills connect to your profile"
                + (f", {transfer_count} via skill transfer" if transfer_count else "")
            ),
        },
    }


def _to_np(embedding: Any) -> np.ndarray | None:
    if embedding is None:
        return None
    return np.asarray(embedding, dtype=np.float32)


def discover(
    families: Sequence[Any],
    seeker_skills: dict[str, tuple[ProficiencyLevel | None, float | None]],
    graph: SkillGraph,
    profile_embedding: Any,
    skill_embeddings: dict[str, Any],
    target_family: Any | None,
    preset_names: Sequence[str] = (),
) -> dict[str, Any]:
    """Affinity-ranked alternative careers with threshold filtering (plan §11)."""
    settings = get_settings()
    tau = settings.discovery_threshold
    families_by_id = {f.id: f for f in families}
    target_id = getattr(target_family, "id", None)
    target_name = (getattr(target_family, "name", None) or "").lower()

    computed: list[dict[str, Any]] = []
    for family in sorted(families, key=lambda f: f.name.lower()):
        if family.id == target_id or family.name.lower() == target_name:
            continue  # never suggest the current direction back
        entry = affinity_for_family(
            family,
            seeker_skills,
            graph,
            profile_embedding,
            skill_embeddings,
            target_family,
            families_by_id,
        )
        if entry is not None:
            computed.append(entry)

    computed.sort(key=lambda e: (-e["affinity"], e["family"].lower()))

    suggestions = [e for e in computed if e["affinity"] >= tau]

    # Presets: rendered with the exact same math (plan §11) — lookup by name
    wanted = {p.lower().strip() for p in preset_names if p and p.strip()}
    presets = [e for e in computed if e["family"].lower() in wanted]

    return {
        "threshold": tau,
        "target_family": getattr(target_family, "name", None),
        "suggestions": suggestions,
        "presets": presets,
        "explored": len(computed),
    }
