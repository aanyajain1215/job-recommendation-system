"""Skill graph traversal + M1 graph embeddings (plan §5/§7/§8).

M1: PyTorch Relational GraphSAGE encoder over a directed Skill-Role-Project
heterogeneous graph, capturing multi-hop structural dependencies
(e.g. Python -> Pandas -> Data Analyst role). Inductive GNN embeddings are
initialized from M0 BGE features and trained via contrastive link prediction.

Edges (curated/DB): prereq, transfer, supersedes.
Learned: GNN skill embeddings for multi-hop transfer similarity (cosine).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np

from app.models.enums import SkillEdgeType

log = logging.getLogger(__name__)
ML_DATA_DIR = Path(__file__).resolve().parents[2] / "ml" / "data"
ARTIFACT_DIR = Path(__file__).resolve().parents[2] / "ml" / "artifacts"


@dataclass
class Edge:
    src: str            # canonical skill name (lowercase key)
    dst: str
    edge_type: SkillEdgeType
    weight: float = 1.0
    source: str = "seed"
    approved: bool = True


@dataclass
class SkillGraph:
    edges: list[Edge] = field(default_factory=list)

    def of_type(self, edge_type: SkillEdgeType) -> list[Edge]:
        return [e for e in self.edges if e.edge_type == edge_type and e.approved]

    def prereqs_of(self, skill: str) -> list[str]:
        key = skill.lower().strip()
        return [e.src for e in self.of_type(SkillEdgeType.PREREQ) if e.dst == key]

    def transfers_to(self, skill: str) -> list[str]:
        """Skills whose holders can transfer INTO `skill` (plan §7/§8)."""
        key = skill.lower().strip()
        return [e.src for e in self.of_type(SkillEdgeType.TRANSFER) if e.dst == key]

    def topological_order(self, wanted: list[str]) -> list[str]:
        """Order `wanted` so prerequisites come first (plan §7 roadmap steps).

        Deterministic: Kahn's algorithm with lexicographic tie-break; skills
        outside `wanted` that are prerequisites are pulled in and included so
        the roadmap never has an unreachable first step. Cycles degrade to
        input order rather than raising.
        """
        wanted_keys = [w.lower().strip() for w in wanted if w and w.strip()]
        wanted_set = set(wanted_keys)
        prereq_edges = self.of_type(SkillEdgeType.PREREQ)

        # include prerequisites of wanted skills (transitively, depth-capped)
        frontier = list(wanted_set)
        seen = set(wanted_set)
        for _ in range(6):  # bounded expansion, avoids runaway graphs
            added = False
            for e in prereq_edges:
                if e.dst in seen and e.src not in seen:
                    seen.add(e.src)
                    frontier.append(e.src)
                    added = True
            if not added:
                break

        nodes = sorted(seen)
        indegree = {n: 0 for n in nodes}
        outs: dict[str, list[str]] = {n: [] for n in nodes}
        for e in prereq_edges:
            if e.src in indegree and e.dst in indegree:
                outs[e.src].append(e.dst)
                indegree[e.dst] += 1

        ready = sorted(n for n in nodes if indegree[n] == 0)
        order: list[str] = []
        while ready:
            node = ready.pop(0)
            order.append(node)
            for nxt in sorted(outs[node]):
                indegree[nxt] -= 1
                if indegree[nxt] == 0:
                    ready.append(nxt)
            ready.sort()

        cyclic = [n for n in nodes if n not in set(order)]
        result = order + sorted(cyclic)
        # keep wanted skills in result, prerequisites first
        return [s for s in result if s in wanted_set] + [s for s in result if s not in wanted_set]


@lru_cache
def load_seed_graph() -> SkillGraph:
    """Load curated prereq/transfer edges from ml/data/skill_prereqs.yaml."""
    path = ML_DATA_DIR / "skill_prereqs.yaml"
    edges: list[Edge] = []
    if path.exists():
        try:
            import yaml  # noqa: PLC0415

            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            for row in data if isinstance(data, list) else []:
                etype = str(row.get("type", "prereq")).lower()
                edge_type = {
                    "prereq": SkillEdgeType.PREREQ,
                    "transfer": SkillEdgeType.TRANSFER,
                    "supersedes": SkillEdgeType.SUPERSEDES,
                }.get(etype, SkillEdgeType.PREREQ)
                edges.append(
                    Edge(
                        src=str(row["from"]).lower().strip(),
                        dst=str(row["to"]).lower().strip(),
                        edge_type=edge_type,
                        weight=float(row.get("weight", 1.0)),
                        source=str(row.get("source", "seed")),
                        approved=bool(row.get("approved", True)),
                    )
                )
        except Exception:
            log.exception("Failed to load skill_prereqs.yaml")
    return SkillGraph(edges=edges)


def fetch_graph(db) -> SkillGraph:
    """Merge DB edges (authoritative, admin-approved) over the YAML seed."""
    from app.models.skill import Skill  # noqa: PLC0415
    from app.models.skill_graph import SkillEdge  # noqa: PLC0415
    from sqlalchemy import select  # noqa: PLC0415

    graph = load_seed_graph()
    try:
        rows = db.execute(
            select(SkillEdge, Skill).join(Skill, SkillEdge.from_skill_id == Skill.id)
        ).all()
        # fetch all skill names once for dst resolution
        all_skills = {s.id: s.name.lower().strip() for s in db.query(Skill).all()}
        for edge, _src in rows:
            dst = all_skills.get(edge.to_skill_id)
            src = all_skills.get(edge.from_skill_id)
            if src and dst:
                graph.edges.append(
                    Edge(
                        src=src,
                        dst=dst,
                        edge_type=edge.edge_type,
                        weight=float(edge.weight),
                        source=edge.source,
                        approved=bool(edge.approved),
                    )
                )
    except Exception:
        log.exception("Failed to fetch skill edges from DB; using seed graph only")
    return graph


def _version_num(path: Path) -> int:
    digits = "".join(ch for ch in path.stem.rsplit("_v", 1)[-1] if ch.isdigit())
    return int(digits) if digits else -1


@lru_cache
def _load_embedding_payload() -> dict | None:
    """Newest skill-embedding artifact by numeric version (v10 > v7)."""
    import os

    if str(os.getenv("SKILL_GRAPH_DISABLE_EMBEDDINGS", "")).strip().lower() in {"1", "true", "yes"}:
        return None
    try:
        import joblib  # noqa: PLC0415
    except Exception:
        return None
    candidates = sorted(ARTIFACT_DIR.glob("skill2vec_v*.joblib"), key=_version_num)
    if not candidates:
        candidates = sorted(ARTIFACT_DIR.glob("skillgraph_gnn_v*.joblib"), key=_version_num)
    if not candidates:
        return None
    try:
        payload = joblib.load(candidates[-1])
        return payload if isinstance(payload, dict) else None
    except Exception:
        log.exception("Failed to load skill embedding artifact %s", candidates[-1])
        return None


@lru_cache
def load_embedding_calibration() -> dict | None:
    """Calibration stored with the O*NET GraphSAGE artifact (v7+), if any.

    Maps raw skill-skill cosine to P(related), fitted (isotonic) on held-out
    O*NET pairs with same-job-group hard negatives. Below `min_prob` the
    embedding gives no transfer evidence at all.
    """
    payload = _load_embedding_payload()
    meta = (payload or {}).get("meta") or {}
    cal = meta.get("calibration")
    if isinstance(cal, dict) and cal.get("kind") in ("platt", "isotonic"):
        return cal
    return None


def calibrated_probability(cosine: float, cal: dict) -> float:
    """Raw skill-skill cosine -> calibrated P(related) using the stored fit."""
    if cal.get("kind") == "isotonic":
        return float(np.interp(cosine, cal["x"], cal["y"]))
    return 1.0 / (1.0 + float(np.exp(-(cal["a"] * cosine + cal["b"]))))


@lru_cache
def load_skill_embeddings() -> dict[str, np.ndarray]:
    """Load M1 skill embeddings (newest artifact)."""
    payload = _load_embedding_payload()
    if payload is None:
        return {}
    try:
        vectors = payload.get("vectors")
        if not isinstance(vectors, dict):
            return {}
        out: dict[str, np.ndarray] = {}
        for k, v in vectors.items():
            try:
                out[str(k).lower().strip()] = np.asarray(v, dtype=np.float32)
            except Exception:
                continue
        return out
    except Exception:
        log.exception("Failed to load skill graph embeddings; falling back to edge-only transfer")
        return {}


def _cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    na = float(np.linalg.norm(a))
    nb = float(np.linalg.norm(b))
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def reset_embedding_cache() -> None:
    load_skill_embeddings.cache_clear()
    load_embedding_calibration.cache_clear()
    _load_embedding_payload.cache_clear()


def transfer_similarity(
    graph: SkillGraph,
    possessed: set[str],
    target_skill: str,
    embeddings: dict[str, np.ndarray] | None = None,
) -> float | None:
    """Transfer credit similarity in [0, 1] for a target skill (plan §7, M1 GNN).

    Resolution order:
      1) Direct TRANSFER edge from a possessed skill -> target (strong credit)
      2) Direct PREREQ edge possessed -> target (partial credit, floored so it is
         never penalized below multi-hop embedding similarity)
      3) Multi-hop structural similarity via M1 Relational GraphSAGE embeddings
         over directed Skill-Role-Project graph

    Returns None when no transfer path/evidence exists (caller treats as missing).
    """
    key = target_skill.lower().strip()
    possessed_norm = {p.lower().strip() for p in possessed}
    if key in possessed_norm:
        return None  # exact possession handled by strong/partial credit

    # Compute best multi-hop embedding similarity (used for hybrid/prereq floor)
    emb_sim: float | None = None
    vecs = embeddings if embeddings is not None else load_skill_embeddings()
    if vecs:
        tvec = vecs.get(key)
        if tvec is not None:
            best = -1.0
            for p in possessed_norm:
                pvec = vecs.get(p)
                if pvec is None:
                    continue
                sim = _cosine_sim(pvec, tvec)
                if sim > best:
                    best = sim
            cal = load_embedding_calibration() if embeddings is None else None
            if cal is not None and best > -1.0:
                # calibrated probability that the two skills are related; below
                # min_prob there is no evidence (not a weak "partial transfer")
                prob = calibrated_probability(best, cal)
                emb_sim = prob if prob >= float(cal.get("min_prob", 0.5)) else None
            elif best >= 0.0:
                emb_sim = float(max(0.0, min(1.0, best)))

    for e in graph.of_type(SkillEdgeType.TRANSFER):
        if e.dst == key and e.src in possessed_norm:
            return max(0.65, min(1.0, e.weight))
    for e in graph.of_type(SkillEdgeType.PREREQ):
        if e.dst == key and e.src in possessed_norm:
            # direct prerequisite: floor so it is never penalized below multi-hop neighbors
            base = 0.60 * float(e.weight)
            if emb_sim is not None:
                return float(max(0.0, min(1.0, max(base, emb_sim))))
            return float(max(0.0, min(1.0, base)))

    # M1: multi-hop structural similarity via GraphSAGE/graph embeddings
    if emb_sim is not None:
        return emb_sim
    return None
