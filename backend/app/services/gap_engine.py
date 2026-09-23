"""Skill Gap Engine (plan §8).

Four-class comparison of a profile against one job's skill requirements:

    STRONG        held with strong evidence (proficiency >= intermediate
                  OR years >= 2)
    PARTIAL       held with weaker evidence, OR alias/parent match (holds a
                  direct prerequisite of the wanted skill)
    TRANSFERABLE  transfer similarity >= threshold (graph transfer edge /
                  skill2vec cosine)
    MISSING       otherwise

Pure: operates on `ComponentInputs` — no DB, no LLM, no I/O.  `gap_score`
is `scoring.skill_match(inputs).score` verbatim, so the gap view and the
recommendation card can never disagree (the deterministic engine owns all
numbers; the LLM never touches them).

`classify()` is the single four-class rule — the gap engine AND alternative
career discovery both go through it (one code path, no drift).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.core.config import get_settings
from app.models.enums import ProficiencyLevel
from app.services.scoring import ComponentInputs, skill_match
from app.services.skill_graph import SkillGraph, load_seed_graph

STRONG = "STRONG"
PARTIAL = "PARTIAL"
TRANSFERABLE = "TRANSFERABLE"
MISSING = "MISSING"

_STRONG_PROFICIENCIES = (
    ProficiencyLevel.INTERMEDIATE,
    ProficiencyLevel.ADVANCED,
    ProficiencyLevel.EXPERT,
)


def strong_evidence(
    proficiency: ProficiencyLevel | None,
    years: float | None,
    min_years: float | None = None,
) -> bool:
    """Plan §8 strong rule: proficiency >= intermediate OR years >= 2."""
    if min_years is None:
        min_years = get_settings().gap_strong_min_years
    return proficiency in _STRONG_PROFICIENCIES or (
        years is not None and years >= min_years
    )


def classify(
    key: str,
    seeker_skills: dict[str, tuple[ProficiencyLevel | None, float | None]],
    transfer_similarities: dict[str, float],
    graph: SkillGraph,
    threshold: float,
) -> tuple[str, dict[str, Any]]:
    """Classify one canonical skill name. Returns (status, evidence dict).

    Evidence is preserved verbatim so every claim in the UI is traceable
    back to a profile row or a graph edge (plan §8/§12).
    """
    key = key.lower().strip()
    possessed = set(seeker_skills)

    if key in seeker_skills:
        proficiency, years = seeker_skills[key]
        evidence = {
            "proficiency": proficiency.value if proficiency else None,
            "years": years,
        }
        if strong_evidence(proficiency, years):
            evidence["reason"] = "held with strong evidence"
            return STRONG, evidence
        evidence["reason"] = "held with weak evidence"
        return PARTIAL, evidence

    sim = transfer_similarities.get(key)

    # Direct prerequisite held by the seeker = parent match (plan §8)
    parents = sorted(p for p in graph.prereqs_of(key) if p in possessed)

    if sim is None:
        if parents:
            return PARTIAL, {
                "reason": "holds a prerequisite of this skill",
                "via_skill": parents[0],
            }
        return MISSING, {"reason": "no held or transferable evidence"}

    rounded = round(float(sim), 3)
    if sim >= threshold:
        return TRANSFERABLE, {
            "reason": "transfers into this skill",
            "transfer_similarity": rounded,
        }
    if parents:
        return PARTIAL, {
            "reason": "holds a prerequisite of this skill",
            "via_skill": parents[0],
            "transfer_similarity": rounded,
        }
    return PARTIAL, {
        "reason": "partial transfer only",
        "transfer_similarity": rounded,
    }


@dataclass
class GapItem:
    """One job skill, classified against the profile."""

    skill: str
    status: str
    required: bool
    importance: float
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def weight(self) -> float:
        # Same effective-weight rule as scoring.skill_match (§6)
        return self.importance * (1.6 if self.required else 1.0)


@dataclass
class GapResult:
    items: list[GapItem]
    gap_score: float                     # == SkillMatch score, verbatim
    missing_required: list[str]
    weakest_link: str | None
    reasons: list[str]

    # ---- convenience views (stable ordering = job order) ----
    @property
    def classes(self) -> list[dict[str, Any]]:
        """`SkillGap.classes` JSONB shape: [{skill, status, evidence}]."""
        return [
            {"skill": i.skill, "status": i.status, "evidence": i.evidence}
            for i in self.items
        ]

    @property
    def strong(self) -> list[str]:
        return [i.skill for i in self.items if i.status == STRONG]

    @property
    def partial(self) -> list[str]:
        return [i.skill for i in self.items if i.status == PARTIAL]

    @property
    def transferable(self) -> list[str]:
        return [i.skill for i in self.items if i.status == TRANSFERABLE]

    @property
    def missing(self) -> list[str]:
        return [i.skill for i in self.items if i.status == MISSING]

    @property
    def counts(self) -> dict[str, int]:
        return {
            "strong": len(self.strong),
            "partial": len(self.partial),
            "transferable": len(self.transferable),
            "missing": len(self.missing),
        }


def compare(
    inputs: ComponentInputs,
    *,
    graph: SkillGraph | None = None,
) -> GapResult:
    """Four-class gap for one job (plan §8).

    `inputs` comes from `_ProfileContext.inputs_for(job)` — the exact same
    inputs the deterministic scorer consumed, so the two views agree by
    construction.
    """
    settings = get_settings()
    graph = graph if graph is not None else load_seed_graph()

    items: list[GapItem] = []
    for req in inputs.job_skills:
        status, evidence = classify(
            req.name,
            inputs.seeker_skills,
            inputs.transfer_similarities,
            graph,
            settings.transfer_similarity_threshold,
        )
        items.append(
            GapItem(
                skill=req.name,
                status=status,
                required=bool(req.is_required),
                importance=float(req.importance_weight or 1.0),
                evidence=evidence,
            )
        )

    missing_required = [
        i.skill for i in items if i.required and i.status == MISSING
    ]

    # Weakest link: highest-weight missing skill (deterministic tie-break:
    # required first, then name)
    missing_items = [i for i in items if i.status == MISSING]
    if missing_items:
        weakest = min(
            missing_items,
            key=lambda i: (-i.weight, 0 if i.required else 1, i.skill.lower()),
        )
        weakest_link: str | None = weakest.skill
    else:
        weakest_link = None

    # gap_score == SkillMatch, verbatim (plan §8: the score is the score)
    detail = skill_match(inputs)

    counts = {
        "strong": sum(1 for i in items if i.status == STRONG),
        "partial": sum(1 for i in items if i.status == PARTIAL),
        "transferable": sum(1 for i in items if i.status == TRANSFERABLE),
        "missing": sum(1 for i in items if i.status == MISSING),
    }
    reasons = [
        (
            f"{counts['strong']} strong, {counts['partial']} partial, "
            f"{counts['transferable']} transferable, {counts['missing']} missing"
        )
    ]
    if missing_required:
        reasons.append("Missing required: " + ", ".join(missing_required))
    if weakest_link:
        reasons.append(f"Weakest link: {weakest_link}")

    return GapResult(
        items=items,
        gap_score=detail.score,
        missing_required=missing_required,
        weakest_link=weakest_link,
        reasons=reasons,
    )
