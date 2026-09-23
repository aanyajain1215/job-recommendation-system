"""Career Roadmap Generator (plan §9).

Input: a GapResult for one job.  Output: ordered skill/project steps with
deterministic effort estimates, phase grouping, and a shadow-scored
readiness-after — everything the /recommendations/{job_id}/roadmap route
persists into career_paths / career_path_steps.

Rules (all deterministic, plan §9):
  * Candidates  = missing required skills ∪ weak partials (importance >= τ)
  * Possessed-strong (STRONG) skills never appear in a roadmap
  * Ordering    = Kahn topo sort over prereq edges, tie-break:
                  (relatedness to possessed desc, importance desc, name)
  * A project step after every 2 skill steps — skipped when the seeker
    already has a qualifying (recent, overlapping) project
  * Effort      = base[category] × difficulty × (1 − 0.4·max_cos_to_possessed)
                  clamped to [8, 120] hours
  * Bands       = <30 Low, 30–70 Medium, >70 High
  * Phases      = greedy pack ≤ 25 h each (a single larger step stands alone)
  * Readiness   = shadow scoring with the roadmap's skills applied — the
                  SAME shadow mechanism as the simulator (one code path)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.core.config import get_settings
from app.models.enums import ProficiencyLevel, SkillEdgeType
from app.services.explanation import readiness_from_score
from app.services.gap_engine import MISSING, PARTIAL, GapResult
from app.services.recommender import _ProfileContext
from app.services.scoring import ComponentInputs, score_pair
from app.services.skill_graph import SkillGraph, transfer_similarity
from app.services.simulator import _fresh_shadow

# Effort model (plan §9): base hours by skill category
BASE_HOURS: dict[str, float] = {
    "language": 80.0,
    "framework": 60.0,
    "database": 50.0,
    "cloud": 70.0,
    "devops": 70.0,
    "ml": 90.0,
    "soft": 30.0,
}
DEFAULT_BASE_HOURS = 50.0
# Common taxonomy spellings -> base-hours keys (plan §9 categories)
CATEGORY_ALIASES: dict[str, str] = {
    "programming": "language",
    "languages": "language",
    "frontend": "framework",
    "backend": "framework",
    "web": "framework",
    "data": "database",
    "db": "database",
    "ai": "ml",
    "mlops": "devops",
    "ops": "devops",
    "tooling": "tools",
    "tools": "tools",
    "softskill": "soft",
    "softskills": "soft",
    "methodology": "soft",
    "systems": "systems",
}
# Partial candidates already hold adjacent evidence -> less effort
DIFFICULTY_MISSING = 1.0
DIFFICULTY_PARTIAL = 0.7
EFFORT_MIN_HOURS = 8.0
EFFORT_MAX_HOURS = 120.0
PROJECT_RECENT_DAYS = 365


@dataclass
class RoadmapStep:
    seq: int
    kind: str                      # "skill" | "project"
    title: str
    skill: str | None              # canonical skill name (skill steps)
    category: str | None
    est_hours: float
    rationale: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "kind": self.kind,
            "title": self.title,
            "skill": self.skill,
            "category": self.category,
            "est_hours": self.est_hours,
            "rationale": self.rationale,
        }


@dataclass
class RoadmapPhase:
    label: str
    est_hours: float
    steps: list[RoadmapStep] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "est_hours": self.est_hours,
            "steps": [s.as_dict() for s in self.steps],
        }


@dataclass
class RoadmapResult:
    steps: list[RoadmapStep]
    phases: list[RoadmapPhase]
    candidates: list[str]
    effort_band: str
    total_hours: float
    readiness_before: dict[str, Any]
    readiness_after: dict[str, Any]
    summary: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "steps": [s.as_dict() for s in self.steps],
            "phases": [p.as_dict() for p in self.phases],
            "candidates": list(self.candidates),
            "effort_band": self.effort_band,
            "total_hours": self.total_hours,
            "readiness_before": self.readiness_before,
            "readiness_after": self.readiness_after,
            "summary": self.summary,
        }


# ---------------------------------------------------------------------------
# Effort model
# ---------------------------------------------------------------------------

def base_hours_for(category: str | None) -> float:
    if not category:
        return DEFAULT_BASE_HOURS
    key = category.strip().lower()
    key = CATEGORY_ALIASES.get(key, key)
    return BASE_HOURS.get(key, DEFAULT_BASE_HOURS)


def effort_hours(
    category: str | None, difficulty: float, max_cos_to_possessed: float
) -> float:
    """base[category] × difficulty × (1 − 0.4·max_cos), clamped [8, 120]."""
    cos = max(0.0, min(1.0, float(max_cos_to_possessed)))
    hours = base_hours_for(category) * difficulty * (1.0 - 0.4 * cos)
    return round(max(EFFORT_MIN_HOURS, min(EFFORT_MAX_HOURS, hours)), 1)


def effort_band(total_hours: float) -> str:
    if total_hours < 30.0:
        return "low"
    if total_hours <= 70.0:
        return "medium"
    return "high"


# ---------------------------------------------------------------------------
# Candidate set + deterministic ordering
# ---------------------------------------------------------------------------

def roadmap_candidates(gap: GapResult) -> dict[str, dict[str, Any]]:
    """missing required ∪ weak partials (plan §9).

    Weak partial = PARTIAL with importance >= settings threshold (parent
    matches included — the seeker doesn't hold the wanted skill itself).
    STRONG skills are excluded by construction.
    """
    settings = get_settings()
    threshold = settings.roadmap_weak_partial_importance
    candidates: dict[str, dict[str, Any]] = {}
    for item in gap.items:
        key = item.skill.lower().strip()
        if item.status == MISSING and item.required:
            candidates[key] = {
                "name": item.skill,
                "importance": item.importance,
                "kind": "missing",
            }
        elif item.status == PARTIAL and item.importance >= threshold:
            candidates[key] = {
                "name": item.skill,
                "importance": item.importance,
                "kind": "weak_partial",
            }
    return candidates


def order_candidates(
    candidates: dict[str, dict[str, Any]],
    inputs: ComponentInputs,
    graph: SkillGraph,
) -> list[str]:
    """Kahn topo sort over in-candidate prereq edges (plan §9).

    Ready-set tie-break: (−relatedness-to-possessed, −importance, name) —
    fully deterministic, no randomness anywhere.
    """
    possessed = set(inputs.seeker_skills)
    names = sorted(candidates)

    indegree = {n: 0 for n in names}
    outs: dict[str, list[str]] = {n: [] for n in names}
    for e in graph.of_type(SkillEdgeType.PREREQ):
        if e.src in indegree and e.dst in indegree and e.src != e.dst:
            outs[e.src].append(e.dst)
            indegree[e.dst] += 1

    related = {
        n: (transfer_similarity(graph, possessed, n) or 0.0) for n in names
    }

    def sort_key(n: str) -> tuple[float, float, str]:
        return (-related[n], -candidates[n]["importance"], n)

    ready = sorted((n for n in names if indegree[n] == 0), key=sort_key)

    order: list[str] = []
    pending = list(ready)
    while pending:
        # deterministic pick: best tie-break among currently-ready nodes
        node = min(pending, key=sort_key)
        pending.remove(node)
        order.append(node)
        for nxt in sorted(outs[node]):
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                pending.append(nxt)

    # cycles degrade to (deterministic) name order rather than raising
    order.extend(n for n in names if n not in set(order))
    return [candidates[n]["name"] for n in order if n in candidates]


def _has_qualifying_project(profile: Any, candidate_keys: set[str]) -> bool:
    """Recent project already demonstrating a candidate skill (plan §9)."""
    now = datetime.now(timezone.utc)
    for row in profile.project_rows or []:
        overlap = {
            str(s).lower().strip() for s in (row.detected_skills or [])
        } & candidate_keys
        if not overlap:
            continue
        created = getattr(row, "created_at", None)
        if created is not None:
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            if (now - created).days > PROJECT_RECENT_DAYS:
                continue
        return True
    return False


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

def build_roadmap(
    profile: Any,
    job: Any,
    gap: GapResult,
    inputs: ComponentInputs,
    graph: SkillGraph,
) -> RoadmapResult:
    """Full roadmap for one profile↔job route (plan §9)."""
    settings = get_settings()
    candidates = roadmap_candidates(gap)
    ordered_names = order_candidates(candidates, inputs, graph)
    possessed = set(inputs.seeker_skills)
    candidate_keys = {n.lower().strip() for n in ordered_names}

    skip_projects = _has_qualifying_project(profile, candidate_keys)
    every_n = max(1, settings.roadmap_project_every_n_skills)

    steps: list[RoadmapStep] = []
    pending_for_project: list[str] = []
    skill_count = 0

    for name in ordered_names:
        key = name.lower().strip()
        meta = candidates.get(key, {"name": name, "importance": 1.0, "kind": "missing"})
        difficulty = (
            DIFFICULTY_PARTIAL if meta["kind"] == "weak_partial" else DIFFICULTY_MISSING
        )
        max_cos = transfer_similarity(graph, possessed, name) or 0.0

        # category comes from the matching job requirement (inputs_for data)
        category = next(
            (r.category for r in inputs.job_skills if r.name.lower().strip() == key),
            None,
        )
        hours = effort_hours(category, difficulty, max_cos)

        steps.append(
            RoadmapStep(
                seq=len(steps) + 1,
                kind="skill",
                title=f"Learn {name}",
                skill=name,
                category=category,
                est_hours=hours,
                rationale={
                    "gap_kind": meta["kind"],
                    "importance": meta["importance"],
                    "difficulty": difficulty,
                    "max_cos_to_possessed": round(max_cos, 3),
                    "reason": (
                        "required and missing"
                        if meta["kind"] == "missing"
                        else f"weak partial (importance {meta['importance']:.1f})"
                    ),
                },
            )
        )
        skill_count += 1
        pending_for_project.append(name)

        if not skip_projects and skill_count % every_n == 0:
            joined = " and ".join(pending_for_project)
            steps.append(
                RoadmapStep(
                    seq=len(steps) + 1,
                    kind="project",
                    title=f"Build a project using {joined}",
                    skill=None,
                    category=None,
                    # Practice rides with the phase it belongs to (plan §9
                    # effort model prices skill acquisition, not the demo)
                    est_hours=0.0,
                    rationale={"skills": list(pending_for_project), "type": "apply"},
                )
            )
            pending_for_project = []

    # ---- phase grouping: greedy pack ≤ phase_max_hours ----
    phase_max = settings.roadmap_phase_max_hours
    phases: list[RoadmapPhase] = []
    current: RoadmapPhase | None = None
    current_hours = 0.0
    for step in steps:
        # zero-hour steps (projects) ride with the current phase — only a
        # step that ADDS hours can force a new phase
        would_exceed = (
            current is not None
            and step.est_hours > 0
            and (current_hours + step.est_hours > phase_max)
        )
        if current is None or would_exceed:
            current = RoadmapPhase(label=f"Phase {len(phases) + 1}", est_hours=0.0)
            phases.append(current)
            current_hours = 0.0
        current.steps.append(step)
        current_hours = round(current_hours + step.est_hours, 1)
        current.est_hours = current_hours

    total_hours = round(sum(s.est_hours for s in steps), 1)
    band = effort_band(total_hours)

    # ---- readiness-after: shadow scoring (same mechanism as simulator) ----
    base_ctx = _ProfileContext(profile)
    before_final = score_pair(base_ctx.inputs_for(job)).final
    readiness_before = readiness_from_score(before_final)

    if ordered_names:
        shadow = _fresh_shadow(
            profile,
            {
                "add_skills": [
                    {"name": n, "level": ProficiencyLevel.INTERMEDIATE.value}
                    for n in ordered_names
                ]
            },
        )
        after_final = score_pair(_ProfileContext(shadow).inputs_for(job)).final
    else:
        after_final = before_final
    readiness_after = readiness_from_score(after_final)

    summary = (
        f"{len(ordered_names)} skill step(s), "
        f"{sum(1 for s in steps if s.kind == 'project')} project step(s), "
        f"~{total_hours:g}h total ({band} effort); readiness "
        f"{readiness_before['band']} → {readiness_after['band']}."
    )

    return RoadmapResult(
        steps=steps,
        phases=phases,
        candidates=[candidates[k]["name"] for k in sorted(candidate_keys)],
        effort_band=band,
        total_hours=total_hours,
        readiness_before=readiness_before,
        readiness_after=readiness_after,
        summary=summary,
    )
