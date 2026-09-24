"""Pluggable ground-truth preference function (plan §6 M2 bootstrap).

Synthetic seeker archetypes grade (profile, job) pairs from the
*submitted* deterministic score plus transparent archetype tilts — the
sanity floor a trained ranker must at least match.  Seeded RNG keeps the
whole bootstrap reproducible; real interaction rows replace it
incrementally (`interactions.metadata.synthetic` marks ours).

Graded label scale (shared with build_datasets / §16):
    0 negative/dismiss · 1 view · 2 click · 4 save
    6 apply/shortlist-entry · 8 shortlisted/relevant · 9 interview · 10 offer
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from app.services.scoring import ComponentInputs, ScoreResult

LABEL_NEGATIVE = 0
LABEL_VIEW = 1
LABEL_CLICK = 2
LABEL_SAVE = 4
LABEL_APPLY = 6
LABEL_SHORTLIST = 8
LABEL_INTERVIEW = 9
LABEL_OFFER = 10


@dataclass(frozen=True)
class ArchetypePrefs:
    """Tilt preferences for one synthetic seeker archetype."""

    target_family: str
    remote_lean: float = 0.0        # -1 onsite-loving .. +1 remote-loving
    salary_sensitivity: float = 0.5  # 0 tolerant .. 1 picky
    difficulty_tolerance: float = 0.5  # 0 skips hard gaps .. 1 applies anyway


ARCHETYPES: dict[str, ArchetypePrefs] = {
    "backend": ArchetypePrefs("Backend Engineering", remote_lean=0.7, salary_sensitivity=0.6),
    "frontend": ArchetypePrefs("Frontend Engineering", remote_lean=0.8, salary_sensitivity=0.4),
    "devops": ArchetypePrefs("DevOps Engineering", remote_lean=0.3, salary_sensitivity=0.5),
    "data": ArchetypePrefs("Data Science", remote_lean=0.4, salary_sensitivity=0.7),
    "ml": ArchetypePrefs("Machine Learning Engineering", remote_lean=0.5, salary_sensitivity=0.6),
    "fullstack": ArchetypePrefs("Software Engineering", remote_lean=0.6, salary_sensitivity=0.5),
}


def ground_truth_grade(
    inputs: ComponentInputs,
    result: ScoreResult,
    prefs: ArchetypePrefs,
    rng: random.Random | None = None,
) -> float:
    """Grade in [0, 100]: deterministic score + archetype tilts + seeded noise."""
    tilt = 0.0

    # Work-mode lean
    if inputs.job_is_remote:
        tilt += 6.0 * prefs.remote_lean
    else:
        tilt -= 4.0 * prefs.remote_lean

    # Salary: lean on the scored component relative to the neutral prior (70)
    if inputs.job_salary_min is not None and inputs.seeker_salary_min is not None:
        tilt += prefs.salary_sensitivity * (result.components.get("salary", 70.0) - 70.0) * 0.30

    # Family targeting
    if inputs.seeker_target_family and inputs.job_family:
        if inputs.seeker_target_family.strip().lower() == inputs.job_family.strip().lower():
            tilt += 8.0
        elif inputs.family_graph_distance is not None and inputs.family_graph_distance <= 1:
            tilt += 3.0

    # Difficulty: missing required skills repel low-tolerance seekers
    gaps = len(result.skill_detail.missing_required)
    tilt -= (2.5 * prefs.difficulty_tolerance) * gaps
    tilt = max(tilt, -15.0)

    noise = (rng.gauss(0.0, 4.0) if rng is not None else 0.0)
    grade = result.final + tilt + noise
    return max(0.0, min(100.0, grade))


def sample_label(grade: float, rng: random.Random) -> int:
    """Seeded label sampler: grade band × one uniform draw."""
    u = rng.random()
    if grade >= 82.0:
        return LABEL_APPLY if u < 0.75 else LABEL_SAVE
    if grade >= 70.0:
        return LABEL_SAVE if u < 0.60 else LABEL_CLICK
    if grade >= 58.0:
        return LABEL_CLICK if u < 0.60 else LABEL_VIEW
    return LABEL_VIEW if u < 0.80 else LABEL_NEGATIVE
