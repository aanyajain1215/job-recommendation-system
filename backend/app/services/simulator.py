"""What-If Career Simulator (plan §10).

Mutation in -> score deltas out.  The simulator NEVER touches profile rows:
every run works on lightweight `ShadowProfile` duck-types that the very same
`_ProfileContext` / `inputs_for` / `score_pair` path consumes — one code
path with the recommendation feed, and the shadows carry no session
reference at all, so a write is structurally impossible (plan §10 invariant).

Idempotence (property-tested): same (profile, mutation) -> byte-identical
`result_delta`.  Everything is deterministic — mutation application rebuilds
from a fresh shadow copy, embeddings are recomputed in-memory with the same
MiniLM embedder, and all ordering uses explicit tie-breaks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from app.models.enums import ProficiencyLevel, WorkMode
from app.services.embeddings import ensure_job_embeddings, ensure_profile_embedding
from app.services.explanation import readiness_from_score
from app.services.recommender import _ProfileContext
from app.services.rerank import rerank
from app.services.scoring import score_pair

# Eligibility bar for newly_eligible/lost: readiness band "high" (>= 0.75),
# the same band the recommendation card displays (plan §12).
ELIGIBLE_BAND = "high"


# ---------------------------------------------------------------------------
# Shadow profile (duck-types Profile for _ProfileContext — never an ORM row)
# ---------------------------------------------------------------------------

@dataclass
class ShadowSkill:
    name: str


@dataclass
class ShadowSkillRow:
    """Duck-types ProfileSkill (profile.skills rows)."""

    skill: ShadowSkill
    proficiency_level: ProficiencyLevel | None = None
    years_of_experience: float | None = None


@dataclass
class ShadowProjectRow:
    """Duck-types Project (profile.project_rows)."""

    name: str = ""
    detected_skills: list[str] = field(default_factory=list)


@dataclass
class ShadowTargetFamily:
    """Duck-types JobFamily (profile.target_family)."""

    name: str
    parent_id: Any = None


class ShadowProfile:
    """In-memory profile stand-in.  Plain attributes only — no session,
    no ORM state, cannot be flushed or committed anywhere."""

    def __init__(self) -> None:
        self.id: Any = None
        self.user_id: Any = None
        self.headline: str | None = None
        self.bio: str | None = None
        self.raw_resume_text: str | None = None
        self.location: str | None = None
        self.preferred_work_mode: WorkMode | None = None
        self.preferred_locations: list[str] = []
        self.expected_salary_min: int | None = None
        self.expected_salary_max: int | None = None
        self.expected_salary_currency: str | None = None
        self.career_interests: list[str] | None = None
        self.years_of_experience: float | None = None
        self.target_family: ShadowTargetFamily | None = None
        self.skills: list[ShadowSkillRow] = []
        self.project_rows: list[ShadowProjectRow] = []
        self.embedding: list[float] | None = None
        self.embedding_updated_at: Any = None
        self.updated_at: Any = None


def build_shadow(profile: Any) -> ShadowProfile:
    """Fresh, fully-copied shadow of a real profile.  Copies lists so
    mutations can never reach the ORM rows behind them."""
    sh = ShadowProfile()
    sh.id = getattr(profile, "id", None)
    sh.user_id = getattr(profile, "user_id", None)
    sh.headline = profile.headline
    sh.bio = profile.bio
    sh.raw_resume_text = getattr(profile, "raw_resume_text", None)
    sh.location = profile.location
    sh.preferred_work_mode = profile.preferred_work_mode
    sh.preferred_locations = list(profile.preferred_locations or [])
    sh.expected_salary_min = profile.expected_salary_min
    sh.expected_salary_max = profile.expected_salary_max
    sh.expected_salary_currency = profile.expected_salary_currency
    sh.career_interests = list(getattr(profile, "career_interests", None) or []) or None
    sh.years_of_experience = profile.years_of_experience

    tf = getattr(profile, "target_family", None)
    if tf is not None:
        sh.target_family = ShadowTargetFamily(
            name=tf.name, parent_id=getattr(tf, "parent_id", None)
        )

    for ps in profile.skills or []:
        if ps.skill is not None and ps.skill.name:
            sh.skills.append(
                ShadowSkillRow(
                    skill=ShadowSkill(name=ps.skill.name),
                    proficiency_level=ps.proficiency_level,
                    years_of_experience=ps.years_of_experience,
                )
            )

    for row in profile.project_rows or []:
        sh.project_rows.append(
            ShadowProjectRow(
                name=str(getattr(row, "name", "") or ""),
                detected_skills=[str(s) for s in (row.detected_skills or [])],
            )
        )

    emb = getattr(profile, "embedding", None)
    sh.embedding = list(emb) if emb is not None else None
    sh.embedding_updated_at = getattr(profile, "embedding_updated_at", None)
    sh.updated_at = getattr(profile, "updated_at", None)
    return sh


# ---------------------------------------------------------------------------
# Mutation application (plan §10 mutation schema)
# ---------------------------------------------------------------------------

def _as_level(value: Any) -> ProficiencyLevel:
    if isinstance(value, ProficiencyLevel):
        return value
    try:
        return ProficiencyLevel(str(value).lower())
    except ValueError:
        return ProficiencyLevel.INTERMEDIATE


def apply_mutation(shadow: ShadowProfile, mutation: dict[str, Any]) -> ShadowProfile:
    """Apply one validated mutation dict to a shadow (in place).

    Caller always passes a fresh `build_shadow(profile)` copy, which is what
    makes `simulate` idempotent by construction.  Text-relevant mutations
    invalidate the embedding; `simulate` re-embeds the shadow in memory.
    """
    for entry in mutation.get("add_skills") or []:
        name = str(entry.get("name") or "").strip()
        if not name:
            continue
        level = _as_level(entry.get("level"))
        years = entry.get("years")
        key = name.lower()
        existing = next(
            (r for r in shadow.skills if r.skill.name.lower() == key), None
        )
        if existing is not None:
            existing.proficiency_level = level
            if years is not None:
                existing.years_of_experience = float(years)
        else:
            shadow.skills.append(
                ShadowSkillRow(
                    skill=ShadowSkill(name=name),
                    proficiency_level=level,
                    years_of_experience=float(years) if years is not None else None,
                )
            )

    for entry in mutation.get("remove_skills") or []:
        key = str(entry).lower().strip()
        shadow.skills = [
            r for r in shadow.skills if r.skill.name.lower() != key
        ]

    salary = mutation.get("expected_salary")
    if isinstance(salary, dict):
        if salary.get("min") is not None:
            shadow.expected_salary_min = int(salary["min"])
        if salary.get("max") is not None:
            shadow.expected_salary_max = int(salary["max"])
        if salary.get("currency"):
            shadow.expected_salary_currency = str(salary["currency"])

    if mutation.get("location") is not None:
        shadow.location = str(mutation["location"])

    if mutation.get("work_mode") is not None:
        shadow.preferred_work_mode = _as_work_mode(mutation["work_mode"])

    if mutation.get("target_family"):
        shadow.target_family = ShadowTargetFamily(
            name=str(mutation["target_family"])
        )

    project = mutation.get("add_project")
    if isinstance(project, dict):
        skills = project.get("skills") or project.get("detected_skills") or []
        shadow.project_rows.append(
            ShadowProjectRow(
                name=str(project.get("name") or ""),
                detected_skills=[
                    str(s).lower().strip() for s in skills if str(s).strip()
                ],
            )
        )

    # `add_cert` is accepted for schema completeness (plan §10); no scoring
    # component consumes certifications yet, so its score delta is honestly 0.
    _ = mutation.get("add_cert")

    return shadow


def _as_work_mode(value: Any) -> WorkMode:
    if isinstance(value, WorkMode):
        return value
    try:
        return WorkMode(str(value).lower())
    except ValueError:
        return WorkMode.REMOTE


def _fresh_shadow(profile: Any, mutation: dict[str, Any]) -> ShadowProfile:
    """build + mutate + re-embed (in memory) — the one shadow code path
    used by `simulate`, its per-skill counterfactuals, and roadmap
    readiness-after (plan §9/§10: one mechanism, no drift)."""
    shadow = apply_mutation(build_shadow(profile), mutation)
    # Always recompute: MiniLM is deterministic, and this keeps the mutation
    # semantics honest (skill/target text changes move the profile vector).
    shadow.embedding = None
    shadow.embedding_updated_at = None
    ensure_profile_embedding(shadow)
    return shadow


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------

def _score_all(ctx: Any, jobs: Sequence[Any]) -> list[tuple[Any, float]]:
    scored = [(job, rerank(score_pair(ctx.inputs_for(job))).final) for job in jobs]
    # Deterministic order: score desc, then job id
    scored.sort(key=lambda t: (-t[1], str(t[0].id)))
    return scored


def _band_counts(scores: list[float]) -> dict[str, int]:
    counts = {"low": 0, "medium": 0, "high": 0}
    for s in scores:
        counts[readiness_from_score(s)["band"]] += 1
    return counts


def _mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 2) if values else 0.0


def simulate(
    profile: Any,
    jobs: Sequence[Any],
    mutation: dict[str, Any],
    target_job_id: Any = None,
) -> dict[str, Any]:
    """Run a What-If simulation (plan §10).

    Returns the `result_delta` payload:
        {before, after, deltas[], target{..., per_skill[]}, mutation}
    Scores only the top-100 baseline candidates (deterministic order).
    """
    ensure_job_embeddings(jobs)

    base_ctx = _ProfileContext(build_shadow(profile))
    mutated_shadow = _fresh_shadow(profile, mutation)
    new_ctx = _ProfileContext(mutated_shadow)

    baseline = _score_all(base_ctx, jobs)[:100]
    after_scores = dict(
        (str(job.id), score) for job, score in _score_all(new_ctx, [j for j, _ in baseline])
    )

    deltas: list[dict[str, Any]] = []
    for job, before in baseline:
        after = after_scores[str(job.id)]
        band_before = readiness_from_score(before)["band"]
        band_after = readiness_from_score(after)["band"]
        deltas.append(
            {
                "job_id": str(job.id),
                "job_title": job.title,
                "before": round(before, 2),
                "after": round(after, 2),
                "delta": round(after - before, 2),
                "band_before": band_before,
                "band_after": band_after,
                "band_changed": band_before != band_after,
                "newly_eligible": (
                    band_before != ELIGIBLE_BAND and band_after == ELIGIBLE_BAND
                ),
                "lost": band_before == ELIGIBLE_BAND and band_after != ELIGIBLE_BAND,
            }
        )

    # ---- target-role readiness (band(context', target) + per-skill) ----
    target_job = None
    if target_job_id is not None:
        target_job = next(
            (j for j, _ in baseline if str(j.id) == str(target_job_id)), None
        )
    if target_job is None and baseline:
        target_job = baseline[0][0]

    target: dict[str, Any] | None = None
    if target_job is not None:
        before_t = next(b for j, b in baseline if j.id == target_job.id)
        after_t = after_scores[str(target_job.id)]
        per_skill: list[dict[str, Any]] = []
        for entry in mutation.get("add_skills") or []:
            single = _fresh_shadow(profile, {"add_skills": [entry]})
            single_score = rerank(
                score_pair(_ProfileContext(single).inputs_for(target_job))
            ).final
            per_skill.append(
                {
                    "skill": str(entry.get("name") or ""),
                    "score": round(single_score, 2),
                    "band": readiness_from_score(single_score)["band"],
                }
            )
        target = {
            "job_id": str(target_job.id),
            "job_title": target_job.title,
            "before": round(before_t, 2),
            "after": round(after_t, 2),
            "delta": round(after_t - before_t, 2),
            "band_before": readiness_from_score(before_t)["band"],
            "band_after": readiness_from_score(after_t)["band"],
            "per_skill": per_skill,
        }

    before_scores = [b for _, b in baseline]
    after_list = [after_scores[str(j.id)] for j, _ in baseline]

    return {
        "before": {
            "mean_score": _mean(before_scores),
            "band_counts": _band_counts(before_scores),
        },
        "after": {
            "mean_score": _mean(after_list),
            "band_counts": _band_counts(after_list),
        },
        "deltas": deltas,
        "target": target,
        "mutation": dict(mutation),
    }
