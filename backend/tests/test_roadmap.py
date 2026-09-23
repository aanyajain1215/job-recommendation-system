"""Tests for the Career Roadmap Generator (plan §9).

Pure: fakes are ShadowProfile/SimpleNamespace duck-types — no HTTP, no
rows created, corpus untouched.
"""

import json
from types import SimpleNamespace

from app.models.enums import ExperienceLevel, ProficiencyLevel
from app.services.gap_engine import compare
from app.services.recommender import _ProfileContext
from app.services.scoring import JobSkillReq
from app.services.roadmap import EFFORT_MAX_HOURS, EFFORT_MIN_HOURS, build_roadmap
from app.services.skill_graph import load_seed_graph
from app.services.simulator import (
    ShadowProfile,
    ShadowProjectRow,
    ShadowSkill,
    ShadowSkillRow,
    ShadowTargetFamily,
)

from app.core.config import get_settings


def make_profile(skills: dict[str, tuple], projects=None) -> ShadowProfile:
    sh = ShadowProfile()
    sh.headline = "Backend developer"
    sh.bio = "I build web APIs and data pipelines."
    sh.location = "Berlin"
    sh.preferred_locations = []
    sh.preferred_work_mode = None
    sh.years_of_experience = 3.0
    sh.target_family = ShadowTargetFamily(name="Backend Engineering")
    sh.skills = [
        ShadowSkillRow(
            skill=ShadowSkill(name=name),
            proficiency_level=level,
            years_of_experience=years,
        )
        for name, (level, years) in skills.items()
    ]
    sh.project_rows = list(projects or [])
    return sh


def make_job(title: str, skills: list[tuple[str, bool, float]]) -> SimpleNamespace:
    rows = [
        SimpleNamespace(
            skill=SimpleNamespace(name=name, category=category),
            is_required=required,
            importance_weight=importance,
        )
        for name, required, importance, category in skills_full(skills)
    ]
    return SimpleNamespace(
        id=f"job-{title.lower().replace(' ', '-')}",
        title=title,
        skills=rows,
        experience_level=ExperienceLevel.MID,
        is_remote=True,
        location=None,
        salary_min=None,
        salary_max=None,
        salary_currency=None,
        family=None,
        embedding=None,
    )


def skills_full(skills: list[tuple[str, bool, float]]):
    """(name, required, importance) -> with a category hint per skill."""
    categories = {
        "python": "language",
        "fastapi": "framework",
        "docker": "devops",
        "kubernetes": "devops",
        "aws": "cloud",
        "terraform": "devops",
    }
    for name, required, importance in skills:
        yield name, required, importance, categories.get(name.lower())


def build(seeker: dict, job, projects=None):
    profile = make_profile(seeker, projects=projects)
    graph = load_seed_graph()
    ctx = _ProfileContext(profile)
    reqs = [
        JobSkillReq(
            name=row.skill.name,
            category=row.skill.category,
            is_required=row.is_required,
            importance_weight=row.importance_weight,
        )
        for row in job.skills
    ]
    inputs = ctx.inputs_for(job)
    inputs.job_skills = reqs  # exact requirements under test
    gap = compare(inputs, graph=graph)
    return build_roadmap(profile, job, gap, inputs, graph)


class TestRoadmapCandidates:
    def test_possessed_strong_skill_not_in_roadmap(self):
        """Plan §9: proficiency you already hold never becomes a step."""
        seeker = {"python": (ProficiencyLevel.EXPERT, 6.0)}
        job = make_job(
            "Platform Engineer",
            [
                ("Python", True, 1.6),
                ("Kubernetes", True, 1.6),
                ("Docker", True, 1.5),
            ],
        )
        result = build(seeker, job)

        skill_steps = [s.skill for s in result.steps if s.kind == "skill"]
        assert skill_steps, "roadmap must contain steps for the real gaps"
        assert "python" not in [s.lower() for s in skill_steps]
        assert "kubernetes" in [s.lower() for s in skill_steps]
        assert "docker" in [s.lower() for s in skill_steps]

    def test_weak_partial_included_only_above_importance_threshold(self):
        settings = get_settings()
        # Both held weakly (beginner, no years) → PARTIAL; only the one with
        # importance ≥ threshold becomes a roadmap candidate.
        seeker = {
            "python": (ProficiencyLevel.BEGINNER, 0.0),
            "docker": (ProficiencyLevel.BEGINNER, 0.0),
        }
        job = make_job(
            "Fullstack Engineer",
            [
                ("Python", True, settings.roadmap_weak_partial_importance + 0.1),
                ("Docker", False, settings.roadmap_weak_partial_importance - 0.4),
            ],
        )
        result = build(seeker, job)
        names = [s.lower() for s in result.candidates]

        assert "python" in names  # weak partial, importance ≥ 1.4
        assert "docker" not in names  # weak partial but importance < 1.4

    def test_topological_prereq_order(self):
        """python → fastapi prereq edge must order python first, even
        though alphabetically fastapi wins the name tie-break."""
        job = make_job(
            "Backend Engineer",
            [
                ("FastAPI", True, 1.6),
                ("Python", True, 1.6),
            ],
        )
        result = build(seeker={}, job=job)

        skill_steps = [s.skill.lower() for s in result.steps if s.kind == "skill"]
        assert {"python", "fastapi"} <= set(skill_steps)
        assert skill_steps.index("python") < skill_steps.index("fastapi")

    def test_project_step_after_every_two_skill_steps(self):
        job = make_job(
            "DevOps Engineer",
            [
                ("Docker", True, 1.6),
                ("Kubernetes", True, 1.6),
                ("AWS", True, 1.5),
                ("Terraform", True, 1.5),
            ],
        )
        result = build(seeker={}, job=job)

        kinds = [s.kind for s in result.steps]
        assert kinds == ["skill", "skill", "project", "skill", "skill", "project"]
        # project steps reference the two skills they apply
        assert result.steps[2].rationale["skills"] == [
            result.steps[0].skill,
            result.steps[1].skill,
        ]

    def test_qualifying_existing_project_skips_project_steps(self):
        job = make_job(
            "DevOps Engineer",
            [
                ("Docker", True, 1.6),
                ("Kubernetes", True, 1.6),
                ("AWS", True, 1.5),
                ("Terraform", True, 1.5),
            ],
        )
        existing = ShadowProjectRow(
            name="Cluster bootstrap", detected_skills=["docker", "kubernetes"]
        )
        result = build(seeker={}, job=job, projects=[existing])

        assert all(s.kind == "skill" for s in result.steps)


class TestEffortAndPhases:
    def test_effort_clamped_and_banded(self):
        job = make_job(
            "DevOps Engineer",
            [
                ("Docker", True, 1.6),
                ("Kubernetes", True, 1.6),
                ("AWS", True, 1.5),
                ("Terraform", True, 1.5),
            ],
        )
        result = build(seeker={}, job=job)

        for step in result.steps:
            if step.kind == "skill":
                assert EFFORT_MIN_HOURS <= step.est_hours <= EFFORT_MAX_HOURS

        assert result.effort_band in {"low", "medium", "high"}
        assert result.total_hours == round(
            sum(s.est_hours for s in result.steps), 1
        )

        # effort responds to relatedness: holding python cuts fastapi hours
        with_python = build(
            seeker={"python": (ProficiencyLevel.EXPERT, 6.0)},
            job=make_job("Backend Engineer", [("FastAPI", True, 1.6)]),
        )
        without = build(
            seeker={},
            job=make_job("Backend Engineer", [("FastAPI", True, 1.6)]),
        )
        step_a = next(s for s in with_python.steps if s.kind == "skill")
        step_b = next(s for s in without.steps if s.kind == "skill")
        assert step_a.est_hours < step_b.est_hours

    def test_phase_packing_rule(self):
        settings = get_settings()
        cap = settings.roadmap_phase_max_hours
        job = make_job(
            "DevOps Engineer",
            [
                ("Docker", True, 1.6),
                ("Kubernetes", True, 1.6),
                ("AWS", True, 1.5),
                ("Terraform", True, 1.5),
            ],
        )
        result = build(seeker={}, job=job)

        assert result.phases, "at least one phase"
        for phase in result.phases:
            assert phase.label.startswith("Phase ")
            assert phase.est_hours == round(
                sum(s.est_hours for s in phase.steps), 1
            )
            skill_hours = [s.est_hours for s in phase.steps if s.kind == "skill"]
            if len(skill_hours) > 1:
                assert sum(skill_hours) <= cap + 1e-6
            else:
                # a single oversized step stands alone (unavoidable)
                assert phase.est_hours <= max(cap, max(skill_hours, default=0))

        # every step appears exactly once, in order
        flat = [s.seq for phase in result.phases for s in phase.steps]
        assert flat == list(range(1, len(flat) + 1))

    def test_readiness_shadow_and_determinism(self):
        job = make_job(
            "Platform Engineer",
            [
                ("Python", True, 1.6),
                ("Docker", True, 1.6),
                ("Kubernetes", True, 1.6),
            ],
        )
        first = build(seeker={}, job=job)
        second = build(seeker={}, job=job)

        assert json.dumps(first.as_dict(), sort_keys=True) == json.dumps(
            second.as_dict(), sort_keys=True
        )
        for readiness in (first.readiness_before, first.readiness_after):
            assert readiness["band"] in {"low", "medium", "high"}
            assert 0.0 <= readiness["value"] <= 1.0
        # roadmap skills fill real gaps → skill-side readiness cannot regress
        assert first.readiness_after["value"] >= first.readiness_before["value"]

    def test_summary_mentions_band_transition(self):
        job = make_job(
            "DevOps Engineer",
            [("Docker", True, 1.6), ("Kubernetes", True, 1.6)],
        )
        result = build(seeker={}, job=job)
        assert "readiness" in result.summary
        assert "→" in result.summary
