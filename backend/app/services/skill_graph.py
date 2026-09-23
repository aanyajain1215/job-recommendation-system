"""Skill graph traversal (plan §5/§7/§8).

Edges: prereq (A→B = A required before B), transfer (A→B = A credits toward B),
supersedes (A→B = A is newer/replaces B). Sources: curated YAML seed,
skill2vec (M1), admin approval.

Pure helpers operate on edge lists; DB wrappers fetch rows with approval filter.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from app.models.enums import SkillEdgeType

log = logging.getLogger(__name__)
ML_DATA_DIR = Path(__file__).resolve().parents[2] / "ml" / "data"


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


def transfer_similarity(
    graph: SkillGraph,
    possessed: set[str],
    target_skill: str,
) -> float | None:
    """Transfer credit similarity in [0, 1] for a target skill (plan §7).

    Returns None when no transfer path exists (caller treats as missing).
    YAML/DB edges carry weight as the base similarity; a direct transfer edge
    is at least the plan's 0.65 threshold, prereq-only paths score lower.
    """
    key = target_skill.lower().strip()
    if key in {p.lower().strip() for p in possessed}:
        return None  # exact possession handled by strong/partial credit

    for e in graph.of_type(SkillEdgeType.TRANSFER):
        if e.dst == key and e.src in {p.lower().strip() for p in possessed}:
            return max(0.65, min(1.0, e.weight))
    for e in graph.of_type(SkillEdgeType.PREREQ):
        if e.dst == key and e.src in {p.lower().strip() for p in possessed}:
            # holding the prereq gives partial transferability
            return max(0.0, min(1.0, 0.5 * e.weight))
    return None
