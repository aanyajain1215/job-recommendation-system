"""Tests for the What-If Career Simulator (plan §10).

Read-only against the shared corpus: creates no rows (teardown-free by
construction) and asserts the plan's hard invariant — profile rows are
never touched — plus idempotence: the same mutation twice yields
byte-identical result_delta.
"""

import json

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.db import SessionLocal
from app.models.enums import ProficiencyLevel
from app.models.job import Job
from app.models.profile import Profile
from app.models.skill import JobSkill, ProfileSkill
from app.models.user import User
from app.services.explanation import readiness_from_score
from app.services.simulator import simulate


def _load() -> tuple[Profile, list[Job]]:
    with SessionLocal() as db:
        user = db.scalar(
            select(User).where(User.email == "aanya.seeker@example.com")
        )
        assert user is not None, "seeded seeker not found"
        profile = db.scalar(
            select(Profile)
            .where(Profile.user_id == user.id)
            .options(
                selectinload(Profile.skills).selectinload(ProfileSkill.skill),
                selectinload(Profile.project_rows),
                selectinload(Profile.target_family),
            )
        )
        assert profile is not None
        jobs = list(
            db.scalars(
                select(Job).options(
                    selectinload(Job.skills).selectinload(JobSkill.skill),
                    selectinload(Job.family),
                    selectinload(Job.company),
                )
            ).all()
        )
        assert jobs, "seeded jobs not found"
        # detach with everything the shadow/context path reads already loaded
        _ = len(profile.skills)
        _ = list(profile.project_rows)
        _ = profile.target_family
        return profile, jobs


DOCKER_MUTATION = {
    "add_skills": [{"name": "Docker", "level": "intermediate", "years": None}]
}


class TestIdempotence:
    def test_same_mutation_twice_is_byte_identical(self):
        profile, jobs = _load()
        first = simulate(profile, jobs, DOCKER_MUTATION)
        second = simulate(profile, jobs, DOCKER_MUTATION)

        assert json.dumps(first, sort_keys=True) == json.dumps(
            second, sort_keys=True
        )

    def test_empty_mutation_yields_zero_deltas(self):
        """No change in → no change out (also proves re-embedding the
        shadow reproduces the stored vector exactly)."""
        profile, jobs = _load()
        result = simulate(profile, jobs, {})

        assert result["deltas"], "candidates were scored"
        for row in result["deltas"]:
            assert row["delta"] == 0.0
            assert row["band_before"] == row["band_after"]
            assert row["newly_eligible"] is False
            assert row["lost"] is False
        if result["target"] is not None:
            assert result["target"]["delta"] == 0.0


class TestProfileInvariant:
    def test_profile_rows_never_mutated(self):
        """Plan §10: the simulator never touches profile rows — a shadow
        gains Docker and loses SQL while the ORM rows stay identical."""
        profile, jobs = _load()
        before_rows = [
            (ps.skill.name, ps.proficiency_level, ps.years_of_experience)
            for ps in profile.skills
        ]
        before_count = len(before_rows)

        simulate(
            profile,
            jobs,
            {
                "add_skills": [
                    {"name": "Docker", "level": "advanced", "years": 1.5}
                ],
                "remove_skills": ["SQL"],
                "expected_salary": {"min": 120000, "max": 160000},
                "location": "Lisbon",
                "target_family": "DevOps Engineering",
            },
        )

        after_rows = [
            (ps.skill.name, ps.proficiency_level, ps.years_of_experience)
            for ps in profile.skills
        ]
        assert after_rows == before_rows
        assert len(after_rows) == before_count


class TestPayload:
    def test_shape_and_delta_math(self):
        profile, jobs = _load()
        result = simulate(profile, jobs, DOCKER_MUTATION)

        assert set(result) == {"before", "after", "deltas", "target", "mutation"}
        assert result["mutation"] == DOCKER_MUTATION
        assert result["deltas"], "top-100 candidates were scored"
        assert len(result["deltas"]) <= 100

        for row in result["deltas"]:
            assert set(row) >= {
                "job_id", "job_title", "before", "after", "delta",
                "band_before", "band_after", "band_changed",
                "newly_eligible", "lost",
            }
            # delta is the before→after difference (2-dp rounding)
            assert abs(row["delta"] - (row["after"] - row["before"])) <= 0.011
            # bands come straight from the §12 readiness mapping
            assert readiness_from_score(row["before"])["band"] == row["band_before"]
            assert readiness_from_score(row["after"])["band"] == row["band_after"]

        for side in ("before", "after"):
            agg = result[side]
            assert set(agg) == {"mean_score", "band_counts"}
            assert set(agg["band_counts"]) == {"low", "medium", "high"}

    def test_target_per_skill_counterfactuals(self):
        profile, jobs = _load()
        mutation = {
            "add_skills": [
                {"name": "Docker", "level": "intermediate"},
                {"name": "AWS", "level": "intermediate"},
            ]
        }
        result = simulate(profile, jobs, mutation)

        target = result["target"]
        assert target is not None, "a target job is always chosen"
        assert set(target) >= {
            "job_id", "job_title", "before", "after", "delta",
            "band_before", "band_after", "per_skill",
        }
        per_skill = target["per_skill"]
        assert [p["skill"] for p in per_skill] == ["Docker", "AWS"]
        for entry in per_skill:
            assert entry["band"] in {"low", "medium", "high"}
            assert 0.0 <= entry["score"] <= 100.0

    def test_band_flip_flagging(self):
        """newly_eligible/lost track crossings of the high band (§10)."""
        profile, jobs = _load()
        result = simulate(profile, jobs, DOCKER_MUTATION)
        for row in result["deltas"]:
            if row["newly_eligible"]:
                assert row["band_after"] == "high"
                assert row["band_before"] != "high"
            if row["lost"]:
                assert row["band_before"] == "high"
                assert row["band_after"] != "high"
            assert not (row["newly_eligible"] and row["lost"])


class TestMutationSchema:
    def test_proficiency_level_strings_accepted(self):
        profile, jobs = _load()
        result = simulate(
            profile,
            jobs,
            {"add_skills": [{"name": "Terraform", "level": "beginner"}]},
        )
        assert result["deltas"]


def test_strong_level_from_enum():
    assert ProficiencyLevel.ADVANCED.value == "advanced"
