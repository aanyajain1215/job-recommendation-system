"""Project ↔ job relevance mapping (plan §13/§14) — fully deterministic.

``project_relevance(project, job) = Σ credit over the job's skills using the
project's detected skills`` with required skills weighted ×1.6 (same
effective-weight rule as the scoring engine), banded:

    ≥ 70 → "Very high"   50–69 → "High"   35–49 → "Moderate"   < 35 → "Low"

Thresholds are module constants (config-overridable, unit-tested at the
exact boundaries).  Surfaces (§14, both directions):
- job side: ``GET /jobs/{id}/project-map`` + ``job.project_relevance``
  ("Powered by: Solar PV System — Very high") on cards;
- profile side: ``GET /profiles/me/project-benefits``
  ("This project benefits: Full-Stack Developer (Very high), …").
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable
from uuid import UUID

from app.services.scoring import JobSkillReq

# Band thresholds (plan §13 example classes map exactly to these labels).
THRESHOLDS: dict[str, float] = {
    "Very high": 70.0,
    "High": 50.0,
    "Moderate": 35.0,
    # below "Moderate" => "Low"
}
MIN_SURFACE_SCORE = 35.0  # never surface "Powered by" for a Low band (§14)


def band_for(score: float) -> str:
    """Deterministic band label for a relevance score in [0, 100]."""
    if score >= THRESHOLDS["Very high"]:
        return "Very high"
    if score >= THRESHOLDS["High"]:
        return "High"
    if score >= THRESHOLDS["Moderate"]:
        return "Moderate"
    return "Low"


def score_project(
    project_skills: Iterable[str],
    job_skills: list[JobSkillReq],
) -> tuple[float, list[str]]:
    """(score 0..100, matched job skills) — required skills weighted ×1.6."""
    ps = {str(s).lower().strip() for s in (project_skills or []) if str(s).strip()}
    if not ps or not job_skills:
        return 0.0, []

    total = 0.0
    gained = 0.0
    matched: list[str] = []
    for req in job_skills:
        weight = float(req.importance_weight or 1.0) * (1.6 if req.is_required else 1.0)
        total += weight
        if req.name.lower().strip() in ps:
            gained += weight
            matched.append(req.name)

    if total <= 0:
        return 0.0, []
    return round(100.0 * gained / total, 1), matched


@dataclass
class ProjectRelevance:
    """One project scored against one job (or one family)."""

    project_id: UUID | None
    title: str
    score: float
    band: str
    matched_skills: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "project_id": str(self.project_id) if self.project_id else None,
            "title": self.title,
            "score": self.score,
            "band": self.band,
            "matched_skills": list(self.matched_skills),
        }


def rank_projects(projects: Iterable[Any], job_skills: list[JobSkillReq]) -> list[ProjectRelevance]:
    """Score every profile project against the job; best first, id tie-break."""
    rows: list[ProjectRelevance] = []
    for project in projects or []:
        skills = set(getattr(project, "detected_skills", None) or [])
        score, matched = score_project(skills, job_skills)
        rows.append(
            ProjectRelevance(
                project_id=getattr(project, "id", None),
                title=str(getattr(project, "title", None) or "Untitled project"),
                score=score,
                band=band_for(score),
                matched_skills=matched,
            )
        )
    rows.sort(key=lambda r: (-r.score, str(r.project_id)))
    return rows


def powered_by_label(projects: Iterable[Any], job_skills: list[JobSkillReq]) -> str | None:
    """Job-card "Powered by: <project> — <band>" (§14). None for Low bands."""
    ranked = rank_projects(projects, job_skills)
    if not ranked:
        return None
    best = ranked[0]
    if best.score < MIN_SURFACE_SCORE:
        return None
    return f"{best.title} — {best.band}"


def family_benefits(
    projects: Iterable[Any],
    families: Iterable[Any],
) -> list[dict[str, Any]]:
    """Profile side (§14): per project, which families it benefits + band.

    Family "requirements" are its core skills — flat required weighting,
    same score function as everything else (deterministic by construction).
    """
    out: list[dict[str, Any]] = []
    for project in projects or []:
        skills = set(getattr(project, "detected_skills", None) or [])
        if not skills:
            continue
        benefits: list[dict[str, Any]] = []
        for family in families or []:
            core = list(getattr(family, "core_skills", None) or [])
            if not core:
                continue
            reqs = [JobSkillReq(name=str(c), is_required=True) for c in core]
            score, _matched = score_project(skills, reqs)
            if score <= 0:
                continue
            benefits.append(
                {
                    "family": str(getattr(family, "name", "")),
                    "score": score,
                    "band": band_for(score),
                }
            )
        benefits.sort(key=lambda b: (-b["score"], b["family"]))
        out.append(
            {
                "project_id": str(getattr(project, "id", "")),
                "title": str(getattr(project, "title", None) or "Untitled project"),
                "benefits": benefits,
            }
        )
    return out
