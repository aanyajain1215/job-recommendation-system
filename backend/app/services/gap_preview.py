"""Per-listing skill-gap preview (plan §8/§17).

Search and AI-search cards show the same matched/missing skill classes as the
recommendation feed, including for transient live (Adzuna) results — which
have no ``jobs`` row and therefore no ``/gap/{id}`` detail page.

Only the three inputs ``scoring.skill_match`` actually reads are gathered:
seeker skills, job requirements and transfer similarities.  No embeddings, no
salary FX, no DB access — annotating a page of cards costs one graph load and
one pure ``skill_match`` call per card, so the search path stays cheap.

Like the recommendation feed, ``missing_skills`` is **required-only** (the
same contract the cards already use); nice-to-have gaps stay out of the
"you're missing" chips.
"""

from __future__ import annotations

from app.models.profile import Profile
from app.schemas.job import JobDetailResponse
from app.services.scoring import (
    ComponentInputs,
    JobSkillReq,
    SkillMatchDetail,
    skill_match,
)
from app.services.skill_graph import SkillGraph, load_seed_graph, transfer_similarity


def seeker_skill_map(profile: Profile) -> dict[str, tuple]:
    """Profile rows → the scorer's canonical `{skill: (proficiency, years)}`."""
    skills: dict[str, tuple] = {}
    for ps in profile.skills or []:
        if ps.skill is None or not ps.skill.name:
            continue
        skills[ps.skill.name.lower().strip()] = (
            ps.proficiency_level,
            ps.years_of_experience,
        )
    return skills


def skill_detail_for(
    requirements: list[JobSkillReq],
    seeker_skills: dict[str, tuple],
    *,
    graph: SkillGraph | None = None,
) -> SkillMatchDetail:
    """Skill-only score/detail for one job — identical rules to the feed."""
    if not requirements or not seeker_skills:
        return SkillMatchDetail(score=0.0)

    graph = graph if graph is not None else load_seed_graph()
    possessed = set(seeker_skills)

    transfers: dict[str, float] = {}
    for req in requirements:
        key = req.name.lower().strip()
        if key in possessed or key in transfers:
            continue
        sim = transfer_similarity(graph, possessed, req.name)
        if sim is not None:
            transfers[key] = sim

    return skill_match(
        ComponentInputs(
            seeker_skills=seeker_skills,
            job_skills=requirements,
            transfer_similarities=transfers,
        )
    )


def annotate_skill_gaps(
    items: list[JobDetailResponse],
    profile: Profile | None,
    *,
    graph: SkillGraph | None = None,
) -> None:
    """Attach matched/missing/transferable skills + skill-match score to cards.

    No-op when there is no profile or the profile lists no skills: an empty
    profile would otherwise mark every requirement as "missing", which is
    noise rather than a disparity.  Items without skill requirements keep the
    neutral (all-empty, ``skill_match_score=None``) shape.
    """
    if profile is None or not items:
        return

    seeker_skills = seeker_skill_map(profile)
    if not seeker_skills:
        return

    graph = graph if graph is not None else load_seed_graph()
    for item in items:
        requirements = [
            JobSkillReq(
                name=skill.skill_name,
                category=skill.category,
                is_required=skill.is_required,
                importance_weight=skill.importance_weight,
            )
            for skill in item.skills
            if skill.skill_name
        ]
        if not requirements:
            continue

        detail = skill_detail_for(requirements, seeker_skills, graph=graph)
        item.matched_skills = list(detail.matched)
        item.missing_skills = list(detail.missing_required)
        item.transferable_skills = list(detail.transferable)
        item.skill_match_score = detail.score
