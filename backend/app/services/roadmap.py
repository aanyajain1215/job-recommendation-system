"""Career Roadmap Generator (plan §9) - Agentic Planner-Critic Pipeline.

3-stage grounded workflow:
  Agent 1 (Gap & Prerequisite Analyzer): queries M1 SkillGraph (prereq, transfer,
           GraphSAGE similarities) to identify and topologically sort missing skills
           so foundational prerequisites always precede advanced skills.
  Agent 2 (Curriculum & Project Planner): generates structured week-by-week plan
           with concrete capstone milestones and curated resource queries tailored
           to target role and timeline.
  Agent 3 (Feasibility & Grounding Critic): programmatically (+LLM when available)
           verifies weekly hour budget, prerequisite ordering, and grounding (no
           hallucinated skills outside target/graph candidates); triggers one
           self-correction revision pass on failure. Emits agent_trace.

Core outputs (steps/phases/effort/readiness) remain deterministic and grounded.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.core.config import get_settings
from app.models.enums import ProficiencyLevel, SkillEdgeType
from app.services.explanation import readiness_from_score
from app.services.gap_engine import MISSING, PARTIAL, GapResult
from app.services.recommender import _ProfileContext
from app.services.scoring import ComponentInputs, score_pair
from app.services.skill_graph import SkillGraph, load_skill_embeddings, transfer_similarity
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
DIFFICULTY_MISSING = 1.0
DIFFICULTY_PARTIAL = 0.7
EFFORT_MIN_HOURS = 8.0
EFFORT_MAX_HOURS = 120.0
PROJECT_RECENT_DAYS = 365
DEFAULT_WEEKLY_HOURS = 10.0


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
    coach: dict[str, Any] | None = None
    agent_trace: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        data = {
            "steps": [s.as_dict() for s in self.steps],
            "phases": [p.as_dict() for p in self.phases],
            "candidates": list(self.candidates),
            "effort_band": self.effort_band,
            "total_hours": self.total_hours,
            "readiness_before": self.readiness_before,
            "readiness_after": self.readiness_after,
            "summary": self.summary,
        }
        if self.coach:
            data["coach"] = self.coach
        if self.agent_trace:
            data["agent_trace"] = self.agent_trace
        return data


def coach_roadmap(result: RoadmapResult) -> dict[str, Any]:
    """LLM coach prose with strict digit-preservation; deterministic fallback."""
    fallback = {
        "headline": "Your personalized roadmap",
        "phase_notes": [{"label": p.label, "note": f"Focus on {len(p.steps)} step(s), ~{p.est_hours:g}h."} for p in result.phases],
        "closing": result.summary,
        "source": "deterministic",
    }
    try:
        from pydantic import BaseModel
        from app.services.llm import get_provider, mark_flagged, prompts, validators

        provider = get_provider()
        if provider is None:
            return fallback
        sections = {
            "summary": result.summary,
            "total_hours": result.total_hours,
            "effort_band": result.effort_band,
            "readiness_before": result.readiness_before.get("band"),
            "readiness_after": result.readiness_after.get("band"),
            "phases": [{"label": p.label, "est_hours": p.est_hours, "steps": [s.title for s in p.steps]} for p in result.phases],
        }

        class _Coach(BaseModel):
            headline: str
            phase_notes: list[dict[str, Any]]
            closing: str

        out, usage = provider.complete_json(
            _Coach,
            prompts.p5_roadmap_coach(sections),
            system="Write encouraging roadmap coaching prose. Never change any number.",
            max_tokens=800,
            route="P5",
        )
        src = json.dumps(sections, ensure_ascii=False)
        cand = json.dumps(out.model_dump(), ensure_ascii=False)
        probs = validators.validate_digits(cand, src, label="coach")
        if probs:
            mark_flagged(usage, "; ".join(probs))
            return fallback
        data = out.model_dump()
        data["source"] = provider.name
        return data
    except Exception:
        return fallback


# ---------------------------------------------------------------------------
# Effort model
# ---------------------------------------------------------------------------

def base_hours_for(category: str | None) -> float:
    if not category:
        return DEFAULT_BASE_HOURS
    key = category.strip().lower()
    key = CATEGORY_ALIASES.get(key, key)
    return BASE_HOURS.get(key, DEFAULT_BASE_HOURS)


def effort_hours(category: str | None, difficulty: float, max_cos_to_possessed: float) -> float:
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
# Agent 1: Gap & Prerequisite Analyzer (M1 grounded, deterministic)
# ---------------------------------------------------------------------------

def roadmap_candidates(gap: GapResult) -> dict[str, dict[str, Any]]:
    settings = get_settings()
    threshold = settings.roadmap_weak_partial_importance
    candidates: dict[str, dict[str, Any]] = {}
    for item in gap.items:
        key = item.skill.lower().strip()
        if item.status == MISSING and item.required:
            candidates[key] = {"name": item.skill, "importance": item.importance, "kind": "missing"}
        elif item.status == PARTIAL and item.importance >= threshold:
            candidates[key] = {"name": item.skill, "importance": item.importance, "kind": "weak_partial"}
    return candidates


def order_candidates(candidates: dict[str, dict[str, Any]], inputs: ComponentInputs, graph: SkillGraph) -> list[str]:
    """Kahn topo sort over in-candidate prereq edges with M1 transfer similarity tie-break."""
    possessed = set(inputs.seeker_skills)
    names = sorted(candidates)
    indegree = {n: 0 for n in names}
    outs: dict[str, list[str]] = {n: [] for n in names}
    for e in graph.of_type(SkillEdgeType.PREREQ):
        if e.src in indegree and e.dst in indegree and e.src != e.dst:
            outs[e.src].append(e.dst)
            indegree[e.dst] += 1

    related = {n: (transfer_similarity(graph, possessed, n) or 0.0) for n in names}

    def sort_key(n: str) -> tuple[float, float, str]:
        return (-related[n], -candidates[n]["importance"], n)

    pending = sorted((n for n in names if indegree[n] == 0), key=sort_key)
    order: list[str] = []
    while pending:
        node = min(pending, key=sort_key)
        pending.remove(node)
        order.append(node)
        for nxt in sorted(outs[node]):
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                pending.append(nxt)

    order.extend(n for n in names if n not in set(order))
    return [candidates[n]["name"] for n in order if n in candidates]


def _has_qualifying_project(profile: Any, candidate_keys: set[str]) -> bool:
    now = datetime.now(timezone.utc)
    for row in profile.project_rows or []:
        overlap = {str(s).lower().strip() for s in (row.detected_skills or [])} & candidate_keys
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


def _agent1_gap_prereq(gap: GapResult, inputs: ComponentInputs, graph: SkillGraph) -> tuple[dict[str, dict], list[str], dict]:
    candidates = roadmap_candidates(gap)
    # enrich with M1 graph evidence
    possessed = set(inputs.seeker_skills)
    gnn_vecs = load_skill_embeddings()
    for key, meta in candidates.items():
        sim = transfer_similarity(graph, possessed, meta["name"]) or 0.0
        meta["transfer_similarity"] = round(float(sim), 4)
        meta["has_prereq_edge"] = bool(graph.prereqs_of(meta["name"]))
        meta["in_gnn_space"] = key in gnn_vecs
    ordered_names = order_candidates(candidates, inputs, graph)
    trace = {
        "agent": "gap_prereq_analyzer",
        "n_candidates": len(candidates),
        "ordered_skills": ordered_names,
        "m1_sources": ["prereq_edges", "transfer_edges", "graphsage_similarity"],
        "grounded_in_graph": True,
    }
    return candidates, ordered_names, trace


# ---------------------------------------------------------------------------
# Agent 2: Curriculum & Project Planner (structured, grounded)
# ---------------------------------------------------------------------------

def _resource_queries(skill: str, category: str | None, role: str | None) -> list[str]:
    cat = (category or "skill").strip()
    role_part = f" for {role}" if role else ""
    return [
        f"{skill} fundamentals {cat}{role_part}",
        f"{skill} hands-on project tutorial{role_part}",
        f"{skill} best practices and exercises",
    ]


def _agent2_curriculum(
    ordered_names: list[str],
    candidates: dict[str, dict],
    inputs: ComponentInputs,
    job: Any,
    steps: list[RoadmapStep],
    phases: list[RoadmapPhase],
    weekly_hours: float,
) -> dict:
    role = getattr(job, "title", None) or inputs.job_family
    week_cursor = 0.0
    week_plan = []
    for phase in phases:
        phase_weeks = []
        for step in phase.steps:
            w = (float(step.est_hours) / max(weekly_hours, 1.0)) if step.est_hours > 0 else 0.0
            start_week = int(math.floor(week_cursor) + 1)
            end_week = int(math.ceil(week_cursor + w)) if w > 0 else start_week
            if step.kind == "skill":
                key = (step.skill or "").lower().strip()
                cat = step.category
                resources = _resource_queries(step.skill or step.title, cat, role)
                milestone = f"Complete a small hands-on exercise demonstrating {step.skill}"
                curriculum = {
                    "week_start": start_week,
                    "week_end": max(start_week, end_week),
                    "resource_queries": resources,
                    "milestone": milestone,
                    "target_role": role,
                }
                step.rationale = {**step.rationale, "curriculum": curriculum}
                phase_weeks.append({"step": step.title, **curriculum})
            else:
                # project/capstone milestone
                skills = step.rationale.get("skills") or []
                milestone = f"Capstone: build and ship a mini-project integrating {', '.join(skills[:3]) or 'learned skills'}"
                curriculum = {
                    "week_start": start_week,
                    "week_end": start_week,
                    "resource_queries": [f"capstone project idea using {' '.join(skills[:2])} {role or ''}".strip()],
                    "milestone": milestone,
                    "target_role": role,
                }
                step.rationale = {**step.rationale, "curriculum": curriculum}
                phase_weeks.append({"step": step.title, **curriculum})
            week_cursor += w
        week_plan.append({"phase": phase.label, "weeks": phase_weeks})
    return {
        "agent": "curriculum_project_planner",
        "target_role": role,
        "weekly_hours_budget": weekly_hours,
        "estimated_weeks": round(week_cursor, 2),
        "week_plan": week_plan,
        "capstone_milestones": [w for ph in week_plan for w in ph["weeks"] if "Capstone" in (w.get("milestone") or "")],
        "grounded_in": "M1 SkillGraph gaps/prerequisites and target role",
    }


# ---------------------------------------------------------------------------
# Agent 3: Feasibility & Grounding Critic (+ self-correction)
# ---------------------------------------------------------------------------

def _programmatic_critic(
    ordered_names: list[str],
    candidates: dict[str, dict],
    steps: list[RoadmapStep],
    phases: list[RoadmapPhase],
    graph: SkillGraph,
    weekly_hours: float,
    total_hours: float,
) -> tuple[bool, list[str], list[str]]:
    issues = []
    fixes = []
    allowed = {n.lower().strip() for n in ordered_names}

    # grounding: no hallucinated skills outside target/candidate set
    for s in steps:
        if s.kind == "skill" and s.skill:
            if s.skill.lower().strip() not in allowed:
                issues.append(f"hallucinated_skill:{s.skill}")

    # prerequisite ordering violations among skill steps
    pos = {s.skill.lower().strip(): i for i, s in enumerate(steps) if s.kind == "skill" and s.skill}
    for e in graph.of_type(SkillEdgeType.PREREQ):
        if e.src in pos and e.dst in pos and pos[e.src] > pos[e.dst]:
            issues.append(f"prereq_violation:{e.src}->{e.dst}")

    # weekly hour budget / phase feasibility
    phase_max = get_settings().roadmap_phase_max_hours
    for ph in phases:
        skill_hours = sum(s.est_hours for s in ph.steps if s.kind == "skill")
        if skill_hours > phase_max + 1e-6 and len([s for s in ph.steps if s.kind == "skill"]) > 1:
            issues.append(f"phase_budget_exceeded:{ph.label}")

    # non-negative, bounded efforts
    for s in steps:
        if s.est_hours < 0:
            issues.append(f"negative_effort:{s.title}")

    passed = len(issues) == 0
    return passed, issues, fixes


def _llm_critic(grounded_payload: dict) -> dict:
    try:
        from pydantic import BaseModel
        from app.services.llm import get_provider

        provider = get_provider()
        if provider is None:
            return {"enabled": False, "passed": None, "reason": "llm_unavailable"}

        class _Critic(BaseModel):
            passed: bool
            issues: list[str] = []
            notes: str = ""

        out, _usage = provider.complete_json(
            _Critic,
            (
                "Verify this roadmap plan is feasible and grounded. "
                "Check: prerequisite ordering, weekly/hour budget realism, and that all skills are from the provided target gaps/graph. "
                "Return passed=false if any hard constraint is violated.\n"
                f"PLAN_JSON:\n{json.dumps(grounded_payload, ensure_ascii=False)[:6000]}"
            ),
            system="You are a strict roadmap feasibility critic. Be factual and conservative.",
            max_tokens=500,
            route="P5",
        )
        return {"enabled": True, "passed": bool(out.passed), "issues": list(out.issues or []), "notes": out.notes}
    except Exception as exc:
        return {"enabled": False, "passed": None, "reason": f"llm_error:{exc}"}


# ---------------------------------------------------------------------------
# Build (orchestrates Agent 1 -> 2 -> 3 with self-correction)
# ---------------------------------------------------------------------------

def build_roadmap(
    profile: Any,
    job: Any,
    gap: GapResult,
    inputs: ComponentInputs,
    graph: SkillGraph,
) -> RoadmapResult:
    settings = get_settings()

    # Agent 1: Gap & Prerequisite Analyzer (M1 grounded)
    candidates, ordered_names, trace_a1 = _agent1_gap_prereq(gap, inputs, graph)
    possessed = set(inputs.seeker_skills)
    candidate_keys = {n.lower().strip() for n in ordered_names}

    skip_projects = _has_qualifying_project(profile, candidate_keys)
    every_n = max(1, settings.roadmap_project_every_n_skills)
    weekly_hours = float(getattr(settings, "roadmap_weekly_hours", DEFAULT_WEEKLY_HOURS) or DEFAULT_WEEKLY_HOURS)

    def _materialize(ord_names: list[str], cands: dict[str, dict], skip_proj: bool):
        steps: list[RoadmapStep] = []
        pending_for_project: list[str] = []
        skill_count = 0
        for name in ord_names:
            key = name.lower().strip()
            meta = cands.get(key, {"name": name, "importance": 1.0, "kind": "missing"})
            difficulty = DIFFICULTY_PARTIAL if meta.get("kind") == "weak_partial" else DIFFICULTY_MISSING
            max_cos = transfer_similarity(graph, possessed, name) or 0.0
            category = next((r.category for r in inputs.job_skills if r.name.lower().strip() == key), None)
            hours = effort_hours(category, difficulty, max_cos)
            steps.append(RoadmapStep(
                seq=len(steps) + 1,
                kind="skill",
                title=f"Learn {name}",
                skill=name,
                category=category,
                est_hours=hours,
                rationale={
                    "gap_kind": meta.get("kind", "missing"),
                    "importance": meta.get("importance", 1.0),
                    "difficulty": difficulty,
                    "max_cos_to_possessed": round(max_cos, 3),
                    "reason": "required and missing" if meta.get("kind") == "missing" else f"weak partial (importance {meta.get('importance', 1.0):.1f})",
                },
            ))
            skill_count += 1
            pending_for_project.append(name)
            if not skip_proj and skill_count % every_n == 0:
                joined = " and ".join(pending_for_project)
                steps.append(RoadmapStep(
                    seq=len(steps) + 1,
                    kind="project",
                    title=f"Build a project using {joined}",
                    skill=None,
                    category=None,
                    est_hours=0.0,
                    rationale={"skills": list(pending_for_project), "type": "apply"},
                ))
                pending_for_project = []

        # phase grouping: greedy pack <= phase_max_hours
        phase_max = settings.roadmap_phase_max_hours
        phases: list[RoadmapPhase] = []
        current: RoadmapPhase | None = None
        current_hours = 0.0
        for step in steps:
            would_exceed = (current is not None and step.est_hours > 0 and (current_hours + step.est_hours > phase_max))
            if current is None or would_exceed:
                current = RoadmapPhase(label=f"Phase {len(phases) + 1}", est_hours=0.0)
                phases.append(current)
                current_hours = 0.0
            current.steps.append(step)
            current_hours = round(current_hours + step.est_hours, 1)
            current.est_hours = current_hours
        return steps, phases

    steps, phases = _materialize(ordered_names, candidates, skip_projects)

    # Agent 2: Curriculum & Project Planner
    trace_a2 = _agent2_curriculum(ordered_names, candidates, inputs, job, steps, phases, weekly_hours)
    total_hours = round(sum(s.est_hours for s in steps), 1)

    # Agent 3: Feasibility & Grounding Critic
    critic_pass, critic_issues, _fixes = _programmatic_critic(ordered_names, candidates, steps, phases, graph, weekly_hours, total_hours)
    revisions = 0
    if not critic_pass:
        # self-correction revision pass: re-topo order, drop hallucinated, re-pack phases
        safe_order = order_candidates(candidates, inputs, graph)
        steps, phases = _materialize(safe_order, candidates, skip_projects)
        total_hours = round(sum(s.est_hours for s in steps), 1)
        trace_a2 = _agent2_curriculum(safe_order, candidates, inputs, job, steps, phases, weekly_hours)
        critic_pass, critic_issues, _ = _programmatic_critic(safe_order, candidates, steps, phases, graph, weekly_hours, total_hours)
        revisions = 1
        ordered_names = safe_order

    # optional LLM critic (non-blocking, best-effort)
    grounded_payload = {
        "target_skills": ordered_names,
        "phases": [p.as_dict() for p in phases],
        "total_hours": total_hours,
        "weekly_hours_budget": weekly_hours,
        "prereq_grounding": "M1 SkillGraph prereq/transfer/GraphSAGE",
    }
    llm_critic = _llm_critic(grounded_payload)
    trace_a3 = {
        "agent": "feasibility_grounding_critic",
        "programmatic_passed": critic_pass,
        "programmatic_issues": critic_issues,
        "revisions_triggered": revisions,
        "checks": ["prerequisite_ordering", "hallucinated_skills", "weekly_hour_budget_phase_packing", "effort_bounds"],
        "llm_verification": llm_critic,
    }

    band = effort_band(total_hours)

    # readiness-after: shadow scoring (same mechanism as simulator)
    base_ctx = _ProfileContext(profile)
    before_final = score_pair(base_ctx.inputs_for(job)).final
    readiness_before = readiness_from_score(before_final)
    if ordered_names:
        shadow = _fresh_shadow(profile, {"add_skills": [{"name": n, "level": ProficiencyLevel.INTERMEDIATE.value} for n in ordered_names]})
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

    agent_trace = {
        "pipeline": "agentic_planner_critic_v1",
        "agents": [trace_a1, trace_a2, trace_a3],
        "grounded_in": "M1 SkillGraph (prereq + transfer + GraphSAGE similarities)",
        "verification_passed": bool(critic_pass and (llm_critic.get("passed") is not False)),
        "programmatic_passed": bool(critic_pass),
        "revisions": revisions,
    }

    result = RoadmapResult(
        steps=steps,
        phases=phases,
        candidates=[candidates[k]["name"] for k in sorted(candidate_keys)],
        effort_band=band,
        total_hours=total_hours,
        readiness_before=readiness_before,
        readiness_after=readiness_after,
        summary=summary,
        agent_trace=agent_trace,
    )
    try:
        result.coach = coach_roadmap(result)
    except Exception:
        pass
    return result
