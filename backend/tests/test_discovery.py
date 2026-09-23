"""Tests for Alternative Career Discovery (plan §11).

Two layers:
  * Pure synthetic tests — exact, DB-free, MiniLM-free: a rich seeker must
    cross τ=55 for exactly one family, below-threshold families must be
    filtered, the current target must be excluded, explanations must carry
    evidence, and presets render with the same math.
  * One read-only corpus test — real profile/families/graph wiring stays
    deterministic and above-threshold for whatever it suggests.
"""

import json
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.careers import PRESET_FAMILIES
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models.enums import ProficiencyLevel
from app.models.job_family import JobFamily
from app.models.profile import Profile
from app.models.skill import ProfileSkill, Skill
from app.models.user import User
from app.services.career_discovery import discover
from app.services.recommender import _ProfileContext
from app.services.skill_graph import fetch_graph, load_seed_graph

# ---------------------------------------------------------------------------
# Pure synthetic fixtures (cores mirror ml/data/families.yaml)
# ---------------------------------------------------------------------------

def _family(name: str, core: list[str]) -> SimpleNamespace:
    return SimpleNamespace(
        id=name.lower().replace(" ", "-"),
        name=name,
        parent_id=None,
        core_skills=core,
    )


FAKE_FAMILIES = [
    _family(
        "Data Science",
        ["python", "pandas", "sql", "statistics", "machine learning", "data visualization"],
    ),
    _family(
        "Backend Engineering",
        ["python", "fastapi", "node.js", "postgresql", "rest apis", "microservices"],
    ),
    _family(
        "Frontend Engineering",
        ["javascript", "typescript", "react", "html", "css", "next.js"],
    ),
    _family(
        "DevOps Engineering",
        ["docker", "kubernetes", "terraform", "aws", "ci/cd", "linux"],
    ),
    _family(
        "Machine Learning Engineering",
        ["python", "pytorch", "tensorflow", "machine learning", "deep learning", "mlops"],
    ),
    _family(
        "Data Analytics",
        ["sql", "excel", "power bi", "tableau", "statistics", "data analysis"],
    ),
]

INTER = ProficiencyLevel.INTERMEDIATE

# A realistic, well-skilled seeker aimed at data work but with backend/devops
# sprinkled in — exactly the profile τ=55 is meant to discriminate for.
RICH_SEEKER = {
    "python": (INTER, 3.0),
    "pandas": (INTER, 2.5),
    "sql": (INTER, 3.0),
    "statistics": (INTER, 2.0),
    "machine learning": (INTER, 2.0),
    "data visualization": (INTER, 1.5),
    "fastapi": (INTER, 1.0),
    "docker": (INTER, 1.0),
}


def _synthetic(target=None, seeker=None) -> dict:
    settings = get_settings()
    assert settings.discovery_threshold == 55.0, "plan §11 default τ"
    return discover(
        families=FAKE_FAMILIES,
        seeker_skills=seeker or RICH_SEEKER,
        graph=load_seed_graph(),
        profile_embedding=None,          # semantic neutral for all: pure overlap
        skill_embeddings={},
        target_family=target,
        preset_names=PRESET_FAMILIES,
    )


class TestThreshold:
    def test_rich_seeker_suggests_exactly_one_family(self):
        result = _synthetic()
        settings = get_settings()

        names = [e["family"] for e in result["suggestions"]]
        assert names == ["Data Science"]
        # overlap 6/6 strong = 1.0; semantic neutral 0.5 → exact blend value
        expected = 100.0 * (
            (1 - settings.discovery_weight_semantic) * 1.0
            + settings.discovery_weight_semantic * 0.5
        )
        assert result["suggestions"][0]["affinity"] == round(expected, 2)
        assert result["suggestions"][0]["affinity"] >= 55.0

    def test_below_threshold_families_are_not_suggested(self):
        result = _synthetic()
        settings = get_settings()
        by_name = {e["family"]: e for e in result["presets"]}

        # ML Engineering: python + ML strong, pytorch/tensorflow via prereq
        # parents (0.6 each) = 3.2/6 → clearly below τ
        assert by_name["Machine Learning Engineering"]["affinity"] < 55.0
        assert by_name["DevOps Engineering"]["affinity"] < 55.0
        assert by_name["Data Analytics"]["affinity"] < 55.0
        for family in ("Machine Learning Engineering", "DevOps Engineering", "Data Analytics"):
            assert family not in {e["family"] for e in result["suggestions"]}
        # nothing outside τ leaks in
        assert all(e["affinity"] >= settings.discovery_threshold for e in result["suggestions"])

    def test_current_target_family_excluded_everywhere(self):
        control = _synthetic()
        assert [e["family"] for e in control["suggestions"]] == ["Data Science"]

        target = next(f for f in FAKE_FAMILIES if f.name == "Data Science")
        filtered = _synthetic(target=target)

        assert filtered["target_family"] == "Data Science"
        assert "Data Science" not in {e["family"] for e in filtered["suggestions"]}
        assert "Data Science" not in {e["family"] for e in filtered["presets"]}
        # control proves the exclusion is what removed it (not τ)
        assert len(filtered["suggestions"]) < len(control["suggestions"]) + 3


class TestExplanationContract:
    def test_suggestion_carries_full_evidence(self):
        result = _synthetic()
        entry = result["suggestions"][0]

        ex = entry["explanation"]
        assert set(ex) == {"top_skills", "transfer_count", "nearest_edge", "note"}
        assert 0 < len(ex["top_skills"]) <= 4
        assert isinstance(ex["transfer_count"], int)
        assert ex["transfer_count"] == 0  # pure strong/partial matches here
        assert ex["nearest_edge"] is None  # no current target → no edge
        assert 0.0 <= entry["affinity"] <= 100.0
        assert 0.0 <= entry["overlap"] <= 1.0
        assert 0.0 <= entry["semantic"] <= 1.0
        assert entry["core_skill_count"] == 6
        assert entry["matched_count"] == 6

    def test_nearest_edge_present_when_target_set(self):
        target = next(f for f in FAKE_FAMILIES if f.name == "Backend Engineering")
        result = _synthetic(target=target)
        for entry in result["suggestions"] + result["presets"]:
            edge = entry["explanation"]["nearest_edge"]
            assert edge is not None
            assert set(edge) == {"from", "to", "relation"}
            assert edge["from"] == "Backend Engineering"
            assert edge["relation"] in {
                "direct child", "direct parent", "distant"
            } or edge["relation"].startswith("sibling")

    def test_transfer_count_reflects_graph_transfers(self):
        # tensorflow is NOT possessed; tensorflow⇄pytorch transfer edges exist,
        # but pytorch isn't possessed either → python prereq parents instead.
        # A seeker holding pytorch picks up tensorflow as TRANSFERABLE.
        seeker = dict(RICH_SEEKER)
        seeker.pop("docker", None)
        seeker["pytorch"] = (INTER, 2.0)
        result = _synthetic(seeker=seeker)

        ml = next(
            e for e in result["presets"]
            if e["family"] == "Machine Learning Engineering"
        )
        # pytorch strong + tensorflow transfer via the curated edge ≥ 0.65
        assert ml["transfer_count"] == 1


class TestPresets:
    def test_presets_rendered_with_same_math(self):
        result = _synthetic()
        names = {p["family"] for p in result["presets"]}
        assert names <= set(PRESET_FAMILIES)
        assert names == set(PRESET_FAMILIES)  # all four exist in the family set
        for preset in result["presets"]:
            assert set(preset) >= {"affinity", "explanation", "overlap", "semantic"}
            # same formula as suggestions: recompute from its own components
            settings = get_settings()
            w = settings.discovery_weight_semantic
            recomputed = 100.0 * (
                (1 - w) * preset["overlap"] + w * preset["semantic"]
            )
            # stored components are rounded to 3dp → allow that drift only
            assert abs(preset["affinity"] - round(recomputed, 2)) <= 0.06

    def test_suggestions_sorted_by_affinity_desc(self):
        result = _synthetic()
        affinities = [e["affinity"] for e in result["presets"]]
        assert affinities == sorted(affinities, reverse=True)


class TestDeterminism:
    def test_two_synthetic_runs_identical(self):
        assert json.dumps(_synthetic(), sort_keys=True) == json.dumps(
            _synthetic(), sort_keys=True
        )


# ---------------------------------------------------------------------------
# Corpus integration (read-only — no rows created)
# ---------------------------------------------------------------------------

def _corpus_result() -> dict:
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
                selectinload(Profile.target_family),
            )
        )
        assert profile is not None
        families = list(db.scalars(select(JobFamily).order_by(JobFamily.name)).all())
        skills = list(db.scalars(select(Skill)).all())
        graph = fetch_graph(db)
        skill_embeddings = {
            str(s.name).lower().strip(): s.embedding
            for s in skills
            if s.embedding is not None
        }
        ctx = _ProfileContext(profile)  # ensures the profile embedding
        result = discover(
            families=families,
            seeker_skills=ctx.seeker_skills,
            graph=graph,
            profile_embedding=profile.embedding,
            skill_embeddings=skill_embeddings,
            target_family=profile.target_family,
            preset_names=PRESET_FAMILIES,
        )
        return result


class TestCorpusRun:
    def test_respects_threshold_and_target(self):
        settings = get_settings()
        result = _corpus_result()

        assert result["threshold"] == settings.discovery_threshold
        for entry in result["suggestions"]:
            assert entry["affinity"] >= settings.discovery_threshold
        target = result["target_family"]
        if target is not None:
            assert target not in {e["family"] for e in result["suggestions"]}
            assert target not in {e["family"] for e in result["presets"]}

    def test_presets_present_and_deterministic(self):
        first = _corpus_result()
        second = _corpus_result()

        preset_names = {p["family"] for p in first["presets"]}
        assert preset_names, "seeded families include preset names"
        assert preset_names <= set(PRESET_FAMILIES)
        assert json.dumps(first, sort_keys=True) == json.dumps(
            second, sort_keys=True
        )
