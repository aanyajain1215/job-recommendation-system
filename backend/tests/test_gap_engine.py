"""Tests for the Skill Gap Engine (plan §8) — four-class comparison.

Pure/service-level: no HTTP, no row creation (corpus stays clean).
The TensorFlow←PyTorch transfer case exercises the curated seed edge
(pytorch → tensorflow weight 0.85 → similarity ≥ 0.65 → TRANSFERABLE).
"""

from app.models.enums import ProficiencyLevel
from app.services.gap_engine import (
    MISSING,
    PARTIAL,
    STRONG,
    TRANSFERABLE,
    compare,
)
from app.services.scoring import ComponentInputs, JobSkillReq, skill_match
from app.services.skill_graph import load_seed_graph, transfer_similarity


def _inputs(seeker: dict, reqs: list[JobSkillReq]) -> ComponentInputs:
    """Mirror _ProfileContext.inputs_for: transfer sims for non-possessed."""
    graph = load_seed_graph()
    transfers: dict[str, float] = {}
    for req in reqs:
        key = req.name.lower().strip()
        if key not in seeker:
            sim = transfer_similarity(graph, set(seeker), req.name)
            if sim is not None:
                transfers[key] = sim
    return ComponentInputs(
        seeker_skills=seeker,
        job_skills=reqs,
        transfer_similarities=transfers,
    )


class TestGapFourClasses:
    def test_tensorflow_transfers_from_pytorch(self):
        """Plan §8: held skill → sibling via transfer edge ≥ 0.65."""
        seeker = {"pytorch": (ProficiencyLevel.ADVANCED, 4.0)}
        inputs = _inputs(seeker, [JobSkillReq(name="TensorFlow", is_required=True)])

        gap = compare(inputs)

        item = gap.items[0]
        assert item.status == TRANSFERABLE
        assert item.evidence["transfer_similarity"] >= 0.65
        assert gap.missing_required == []
        assert "tensorflow" not in [s.lower() for s in gap.missing]

    def test_strong_and_partial_and_missing(self):
        seeker = {
            "python": (ProficiencyLevel.EXPERT, 6.0),
            "html": (ProficiencyLevel.BEGINNER, 0.0),
        }
        reqs = [
            JobSkillReq(name="Python", is_required=True),
            JobSkillReq(name="HTML", is_required=True),
            JobSkillReq(name="Kubernetes", is_required=True),
            JobSkillReq(name="Docker", is_required=False),
        ]
        gap = compare(_inputs(seeker, reqs))

        by_name = {i.skill: i.status for i in gap.items}
        assert by_name["Python"] == STRONG          # expert ≥ intermediate
        assert by_name["HTML"] == PARTIAL           # beginner, no years
        assert by_name["Kubernetes"] == MISSING     # no evidence at all
        assert by_name["Docker"] == MISSING

    def test_parent_match_is_partial(self):
        """Holding a direct prereq (python → fastapi, 0.5×0.9 < 0.65)
        is a parent match: PARTIAL with the via_skill preserved."""
        seeker = {"python": (ProficiencyLevel.ADVANCED, 5.0)}
        inputs = _inputs(seeker, [JobSkillReq(name="FastAPI", is_required=True)])

        gap = compare(inputs)

        assert gap.items[0].status == PARTIAL
        assert gap.items[0].evidence.get("via_skill") == "python"
        assert gap.missing_required == []

    def test_missing_required_and_weakest_link(self):
        seeker = {"python": (ProficiencyLevel.EXPERT, 6.0)}
        reqs = [
            JobSkillReq(name="Python", is_required=True),
            JobSkillReq(name="Kubernetes", is_required=True),
            JobSkillReq(name="Terraform", is_required=False),
        ]
        gap = compare(_inputs(seeker, reqs))

        assert gap.missing_required == ["Kubernetes"]
        # Required missing beats preferred missing on effective weight
        assert gap.weakest_link == "Kubernetes"

    def test_no_missing_means_no_weakest_link(self):
        seeker = {"python": (ProficiencyLevel.EXPERT, 6.0)}
        gap = compare(_inputs(seeker, [JobSkillReq(name="Python")]))
        assert gap.weakest_link is None
        assert gap.counts["missing"] == 0

    def test_gap_score_equals_skill_match_verbatim(self):
        """Plan §8: the gap view and the card can never disagree."""
        seeker = {
            "python": (ProficiencyLevel.INTERMEDIATE, 2.0),
            "pytorch": (ProficiencyLevel.BEGINNER, 0.5),
        }
        reqs = [
            JobSkillReq(name="Python", is_required=True),
            JobSkillReq(name="TensorFlow", is_required=True),
            JobSkillReq(name="Kubernetes", is_required=True),
            JobSkillReq(name="AWS", is_required=False),
        ]
        inputs = _inputs(seeker, reqs)
        gap = compare(inputs)

        assert gap.gap_score == skill_match(inputs).score
        assert 0.0 <= gap.gap_score <= 100.0

    def test_classes_shape_matches_skillgap_jsonb(self):
        seeker = {"python": (ProficiencyLevel.EXPERT, 6.0)}
        gap = compare(_inputs(seeker, [JobSkillReq(name="Python")]))

        classes = gap.classes
        assert len(classes) == 1
        assert set(classes[0]) == {"skill", "status", "evidence"}
        assert classes[0]["status"] == STRONG
        assert "reason" in classes[0]["evidence"]

    def test_deterministic(self):
        seeker = {"pytorch": (ProficiencyLevel.INTERMEDIATE, 2.0)}
        reqs = [
            JobSkillReq(name="TensorFlow", is_required=True),
            JobSkillReq(name="Kubernetes", is_required=True),
        ]
        first = compare(_inputs(seeker, reqs))
        second = compare(_inputs(seeker, reqs))

        assert first.classes == second.classes
        assert first.gap_score == second.gap_score
        assert first.missing_required == second.missing_required
        assert first.weakest_link == second.weakest_link
