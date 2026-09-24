"""Hybrid recommendation pipeline (plan §4/§6/§16, §23 Phase 1).

Pipeline:

1. **Candidate generation** — Reciprocal Rank Fusion (k=60) over three
   independent retrievals: pgvector KNN on embeddings, Postgres FTS
   (`search_vector`), and skill-overlap count.  Each leg is optional and
   skips gracefully when its data is missing; if every leg is empty we fall
   back to recency (previous behavior preserved).
2. **Deterministic scoring** — `scoring.score_pair` computes the 8-component
   score.  The LLM never participates.
3. **Strategy re-rank** — `rerank.rerank` applies `deterministic` /
   `ltr_blend` (no-op until M2 ships; strategy honestly reported).
4. **Diversity** — MMR (λ from settings, default 0.7) + at most 3 jobs per
   job family in the top-10 window.
5. **Exploration** — one deterministic 1-in-6 feed slot per (user, day),
   propensity carried on the item for logging (plan §16). Never slot 0.
6. **Explanation** — §12 contract built verbatim from the scorer output.

Public surface kept per §23: ``ContentRecommender.recommend_jobs(profile,
jobs, limit)`` and cold-start behavior are unchanged from the caller's
point of view.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Sequence
from uuid import UUID

import numpy as np
from sqlalchemy import bindparam, select, text
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings
from app.models.enums import JobStatus, WorkMode
from app.models.job import Job
from app.models.profile import Profile
from app.models.skill import JobSkill, ProfileSkill
from app.services.embeddings import (
    ensure_job_embeddings,
    ensure_profile_embedding,
    to_usd,
)
from app.services.explanation import (
    build_explanation,
    readiness_from_score,
    validate_explanation,
)
from app.services.mmr import (
    apply_family_cap,
    exploration_propensity,
    exploration_should_apply,
    mmr_order,
)
from app.services.rerank import FeatureContext, RankOutcome, build_features, rerank
from app.services.scoring import (
    ComponentInputs,
    JobSkillReq,
    ScoreResult,
    experience_match,
    score_pair,
    skill_match,
)
from app.services.skill_graph import SkillGraph, load_seed_graph, transfer_similarity
from app.schemas.job import JobDetailResponse, JobSkillRequirement
from app.schemas.recommendation import RecommendationFeedResponse, RecommendationItem
from app.schemas.user import CompanySummary

log = logging.getLogger(__name__)

RRF_K = 60
COLD_START_REASON = "Complete your profile skills to get tailored recommendations."
STRATEGY_LABEL = "hybrid_rrf_deterministic"
COLD_STRATEGY_LABEL = "cold_start_neutral_priors"


# ---------------------------------------------------------------------------
# Candidate generation (plan §4: KNN ∪ FTS ∪ skill, fused by RRF)
# ---------------------------------------------------------------------------

def _rrf(leg_rankings: Sequence[Sequence[UUID]], k: int = RRF_K) -> list[UUID]:
    """Reciprocal Rank Fusion over ranked id lists; deterministic tie-break."""
    scores: dict[UUID, float] = {}
    for ranking in leg_rankings:
        for rank, item_id in enumerate(ranking, start=1):
            scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores, key=lambda item_id: (-scores[item_id], str(item_id)))


def _profile_query_text(profile: Profile) -> str:
    parts = [p for p in (profile.headline, profile.bio) if p]
    skill_names = [
        ps.skill.name for ps in (profile.skills or []) if ps.skill is not None
    ]
    if skill_names:
        parts.append(" ".join(skill_names))
    if profile.location:
        parts.append(profile.location)
    target = getattr(profile, "target_family", None)
    if target is not None:
        parts.append(target.name)
    return " ".join(parts).strip()[:1000]


def generate_candidates(db: Session, profile: Profile, limit: int) -> list[Job]:
    """Hybrid candidate generation: KNN ∪ FTS ∪ skill overlap, fused by RRF.

    Returns fully eager-loaded published jobs in fusion order, capped to a
    bounded pool (scoring + diversity run over this pool).  Never raises:
    a failing leg is skipped, and an empty fusion falls back to recency.
    """
    pool_cap = max(limit * 4, 30)
    per_leg = max(limit * 3, 30)
    legs: list[list[UUID]] = []

    # Leg 1: pgvector KNN on profile↔job embeddings
    try:
        ensure_profile_embedding(profile)
        if profile.embedding:
            emb_literal = "[" + ",".join(f"{float(v):.6f}" for v in profile.embedding) + "]"
            rows = db.execute(
                text(
                    "SELECT id FROM jobs "
                    "WHERE status = :st AND embedding IS NOT NULL "
                    "ORDER BY embedding <=> CAST(:emb AS vector) "
                    "LIMIT :k"
                ),
                {"st": JobStatus.PUBLISHED.name, "emb": emb_literal, "k": per_leg},
            ).all()
            if rows:
                legs.append([row[0] for row in rows])
    except Exception:
        log.exception("KNN candidate leg failed; continuing without it")

    # Leg 2: Postgres FTS over the profile's descriptive text
    try:
        query = _profile_query_text(profile)
        if query:
            rows = db.execute(
                text(
                    "SELECT id, ts_rank_cd(search_vector, "
                    "websearch_to_tsquery('english', :q)) AS rnk "
                    "FROM jobs "
                    "WHERE status = :st "
                    "AND search_vector @@ websearch_to_tsquery('english', :q) "
                    "ORDER BY rnk DESC, id LIMIT :k"
                ),
                {"st": JobStatus.PUBLISHED.name, "q": query, "k": per_leg},
            ).all()
            if rows:
                legs.append([row[0] for row in rows])
    except Exception:
        log.exception("FTS candidate leg failed; continuing without it")

    # Leg 3: skill overlap count (SQL-side join, canonical lowercase names)
    try:
        names = [
            ps.skill.name.lower().strip()
            for ps in (profile.skills or [])
            if ps.skill is not None and ps.skill.name
        ]
        if names:
            stmt = text(
                "SELECT j.id AS id, COUNT(*) AS ov "
                "FROM jobs j "
                "JOIN job_skills js ON js.job_id = j.id "
                "JOIN skills s ON s.id = js.skill_id "
                "WHERE j.status = :st AND lower(s.name) IN :names "
                "GROUP BY j.id ORDER BY ov DESC, j.id LIMIT :k"
            ).bindparams(bindparam("names", expanding=True))
            rows = db.execute(
                stmt, {"st": JobStatus.PUBLISHED.name, "names": names, "k": per_leg}
            ).all()
            if rows:
                legs.append([row[0] for row in rows])
    except Exception:
        log.exception("skill candidate leg failed; continuing without it")

    ordered_ids = _rrf(legs) if legs else []
    if not ordered_ids:
        # Fallback: everything published, newest first (previous behavior)
        ordered_ids = list(
            db.scalars(
                select(Job.id)
                .where(Job.status == JobStatus.PUBLISHED)
                .order_by(Job.created_at.desc(), Job.id)
                .limit(pool_cap)
            ).all()
        )
    else:
        ordered_ids = ordered_ids[:pool_cap]

    if not ordered_ids:
        return []

    jobs = db.scalars(
        select(Job)
        .where(Job.id.in_(ordered_ids))
        .options(
            selectinload(Job.company),
            selectinload(Job.skills).selectinload(JobSkill.skill),
            selectinload(Job.applications),
            selectinload(Job.family),
        )
    ).all()
    by_id = {job.id: job for job in jobs}
    # preserve RRF order
    return [by_id[item_id] for item_id in ordered_ids if item_id in by_id]


# ---------------------------------------------------------------------------
# Input assembly (one profile context, per-job ComponentInputs)
# ---------------------------------------------------------------------------

def _job_family_name(job: Job) -> str | None:
    try:
        return job.family.name if job.family is not None else None
    except Exception:
        return None


def _build_job_requirements(job: Job) -> list[JobSkillReq]:
    reqs: list[JobSkillReq] = []
    for js in job.skills or []:
        if js.skill is None or not js.skill.name:
            continue
        reqs.append(
            JobSkillReq(
                name=js.skill.name,
                category=js.skill.category,
                is_required=bool(js.is_required),
                importance_weight=float(js.importance_weight or 1.0),
            )
        )
    return reqs


class _ProfileContext:
    """Everything about the seeker that doesn't change per job."""

    def __init__(self, profile: Profile) -> None:
        self.seeker_skills: dict[str, tuple] = {}
        for ps in profile.skills or []:
            if ps.skill is not None and ps.skill.name:
                self.seeker_skills[ps.skill.name.lower().strip()] = (
                    ps.proficiency_level,
                    ps.years_of_experience,
                )
        self.possessed = set(self.seeker_skills)
        self.graph: SkillGraph = load_seed_graph()
        self.years = profile.years_of_experience

        self.project_skills: set[str] = set()
        try:
            for row in profile.project_rows or []:
                for name in row.detected_skills or []:
                    if name:
                        self.project_skills.add(str(name).lower().strip())
        except Exception:
            pass

        self.preferred_locations = {
            str(p).lower().strip() for p in (profile.preferred_locations or [])
        }
        self.location = profile.location
        self.open_to_remote = profile.preferred_work_mode in (None, WorkMode.REMOTE)

        self.seeker_salary_min = to_usd(
            profile.expected_salary_min, profile.expected_salary_currency
        )
        self.seeker_salary_max = to_usd(
            profile.expected_salary_max, profile.expected_salary_currency
        )
        self.interest_skills = {
            str(i).lower().strip() for i in (profile.career_interests or [])
        }

        try:
            target = profile.target_family
            self.target_family = target.name if target is not None else None
            self.target_family_parent = target.parent_id if target is not None else None
        except Exception:
            self.target_family = None
            self.target_family_parent = None

        ensure_profile_embedding(profile)
        self.profile_embedding = (
            np.asarray(profile.embedding, dtype=np.float32)
            if profile.embedding
            else None
        )

    def inputs_for(self, job: Job) -> ComponentInputs:
        job_reqs = _build_job_requirements(job)

        # transfer similarities for skills the seeker does NOT hold
        transfers: dict[str, float] = {}
        for req in job_reqs:
            key = req.name.lower().strip()
            if key in self.possessed:
                continue
            sim = transfer_similarity(self.graph, self.possessed, req.name)
            if sim is not None:
                transfers[key] = sim

        cosine = None
        if self.profile_embedding is not None and job.embedding:
            job_vec = np.asarray(job.embedding, dtype=np.float32)
            denom = float(
                np.linalg.norm(self.profile_embedding) * np.linalg.norm(job_vec)
            )
            if denom > 0:
                cosine = float(np.dot(self.profile_embedding, job_vec) / denom)

        family = getattr(job, "family", None)
        job_family = family.name if family is not None else None
        job_parent = family.parent_id if family is not None else None

        distance = None
        if (
            self.target_family
            and job_family
            and self.target_family_parent is not None
            and self.target_family_parent == job_parent
        ):
            distance = 1

        job_salary_min = to_usd(job.salary_min, job.salary_currency)
        job_salary_max = to_usd(job.salary_max, job.salary_currency)

        return ComponentInputs(
            semantic_cosine=cosine,
            seeker_skills=self.seeker_skills,
            job_skills=job_reqs,
            transfer_similarities=transfers,
            years_of_experience=self.years,
            job_level=job.experience_level,
            seeker_degree=None,      # job has no degree bar yet → component = 100
            seeker_field=None,
            job_degree=None,
            job_field=None,
            seeker_project_skills=self.project_skills,
            job_is_remote=bool(job.is_remote),
            seeker_location=self.location,
            job_location=job.location,
            seeker_preferred_locations=self.preferred_locations,
            seeker_open_to_remote=self.open_to_remote,
            seeker_salary_min=int(self.seeker_salary_min) if self.seeker_salary_min is not None else None,
            seeker_salary_max=int(self.seeker_salary_max) if self.seeker_salary_max is not None else None,
            job_salary_min=int(job_salary_min) if job_salary_min is not None else None,
            job_salary_max=int(job_salary_max) if job_salary_max is not None else None,
            seeker_target_family=self.target_family,
            job_family=job_family,
            family_graph_distance=distance,
            seeker_interest_skills=self.interest_skills,
        )


def _job_age_days(job: Job, now: datetime) -> float:
    """Days since posting — deterministic M2 context feature (plan §6)."""
    try:
        created = job.created_at
        if created is None:
            return 0.0
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        return max(0.0, (now - created).total_seconds() / 86400.0)
    except Exception:
        return 0.0


def _applicant_count(job: Job) -> float:
    try:
        return float(len(job.applications)) if job.applications is not None else 0.0
    except Exception:
        return 0.0


def _apply_rate(job: Job) -> float:
    """Log-scaled historical apply pressure, bounded to [0, 1]."""
    count = int(_applicant_count(job))
    return round(min(1.0, count / 50.0), 4)


# ---------------------------------------------------------------------------
# Recommender
# ---------------------------------------------------------------------------

class ContentRecommender:
    """Scores/ranks an already-selected candidate pool (plan §4 steps 2–6)."""

    @classmethod
    def recommend_jobs(
        cls,
        profile: Profile,
        jobs: Sequence[Job],
        limit: int = 20,
    ) -> RecommendationFeedResponse:
        completeness = cls.compute_profile_completeness(profile)

        if not jobs:
            return RecommendationFeedResponse(
                items=[],
                total=0,
                profile_completeness_score=completeness,
                recommendation_type="content_based",
                recommendation_strategy=STRATEGY_LABEL,
            )

        has_skills = any(
            ps.skill is not None and ps.skill.name for ps in (profile.skills or [])
        )
        has_text = bool(profile.headline or profile.bio or profile.raw_resume_text)
        if not (has_skills or has_text):
            return cls._cold_feed(profile, jobs, limit, completeness)

        settings = get_settings()
        ctx = _ProfileContext(profile)
        ensure_job_embeddings(jobs)

        scored: list[tuple[Job, ScoreResult, RankOutcome]] = []
        now = datetime.now(timezone.utc)
        for job in jobs:
            inputs = ctx.inputs_for(job)
            result = score_pair(inputs)
            features = build_features(
                inputs,
                result,
                FeatureContext(
                    job_age_days=_job_age_days(job, now),
                    applicant_count=_applicant_count(job),
                    profile_completeness=completeness,
                    historical_apply_rate=_apply_rate(job),
                ),
            )
            outcome = rerank(result, features=features)
            scored.append((job, result, outcome))

        # 1. relevance order — deterministic tie-break on job id
        scored.sort(key=lambda t: (-t[2].final, str(t[0].id)))

        # 2. MMR diversity over a bounded pool
        pool_cap = min(len(scored), max(limit * 4, 24))
        pool = scored[:pool_cap]
        relevance = [t[2].final for t in pool]
        vectors = None
        if all(t[0].embedding for t in pool):
            vectors = np.asarray([t[0].embedding for t in pool], dtype=np.float32)
        positions = mmr_order(relevance, vectors, limit=pool_cap, lamb=settings.mmr_lambda)
        ordered = [pool[i] for i in positions]

        # 3. family cap: ≤3 per family within the top-10 window
        families = [_job_family_name(t[0]) for t in ordered]
        capped_positions = apply_family_cap(
            list(range(len(ordered))),
            families,
            limit=len(ordered),
            family_cap=3,
            cap_window=10,
        )
        ordered = [ordered[p] for p in capped_positions]

        # 4. exploration slot — deterministic per (user, day), never slot 0
        explorer_slot: int | None = None
        slot = max(1, limit // 3)
        if (
            slot < limit
            and len(ordered) > limit
            and exploration_should_apply(
                str(profile.user_id), rate=settings.exploration_rate
            )
        ):
            ordered[slot], ordered[limit] = ordered[limit], ordered[slot]
            explorer_slot = slot

        # 5. build items with explanation contracts
        items: list[RecommendationItem] = []
        for index, (job, result, outcome) in enumerate(ordered[:limit]):
            family = _job_family_name(job)
            contract = build_explanation(
                job.title,
                job.company.name if job.company is not None else None,
                result,
                family=family,
                display_score=outcome.final,
            )
            contract.delta_note = outcome.delta_note
            problems = validate_explanation(contract, result.final)
            if problems:
                log.warning("explanation consistency for job %s: %s", job.id, problems)

            reasons = list(result.skill_detail.reasons)
            if not reasons:
                reasons = [contract.summary]

            is_explorer = index == explorer_slot
            items.append(
                RecommendationItem(
                    job=cls._job_detail(job, outcome.final),
                    match_score=outcome.final,
                    skill_match_score=result.components.get("skill", 0.0),
                    content_similarity_score=result.components.get("semantic", 0.0),
                    matched_skills=list(result.skill_detail.matched),
                    missing_skills=list(result.skill_detail.missing_required),
                    match_reasons=reasons,
                    explanation=contract.as_dict(),
                    readiness=readiness_from_score(outcome.final),
                    family=family,
                    strategy=outcome.strategy,
                    model_version=outcome.model_version,
                    propensity=(
                        exploration_propensity(settings.exploration_rate)
                        if is_explorer
                        else 1.0
                    ),
                )
            )

        first_outcome = scored[0][2]
        return RecommendationFeedResponse(
            items=items,
            total=len(scored),
            profile_completeness_score=completeness,
            recommendation_type="content_based",
            recommendation_strategy=STRATEGY_LABEL,
            strategy=first_outcome.strategy,
            model_version=first_outcome.model_version,
            personalization_note=(
                "Includes 1 exploratory suggestion (1-in-6 feed slots, "
                f"propensity {exploration_propensity(settings.exploration_rate)}) "
                "to surface adjacent career directions."
                if explorer_slot is not None
                else None
            ),
        )

    @classmethod
    def _cold_feed(
        cls,
        profile: Profile,
        jobs: Sequence[Job],
        limit: int,
        completeness: float,
    ) -> RecommendationFeedResponse:
        """Cold start: profile has no skills and no text — neutral priors only.

        Preserves the previous behavior (score from experience fit, single
        completeness nudge as the reason) so onboarding UX doesn't regress.
        """
        items: list[RecommendationItem] = []
        for job in jobs:
            detail = skill_match(ComponentInputs(job_skills=_build_job_requirements(job)))
            exp = experience_match(profile.years_of_experience, job.experience_level)
            score = round(max(30.0, exp * 0.5), 1)
            items.append(
                RecommendationItem(
                    job=cls._job_detail(job, score),
                    match_score=score,
                    skill_match_score=detail.score,
                    content_similarity_score=0.0,
                    matched_skills=[],
                    missing_skills=list(detail.missing_required),
                    match_reasons=[COLD_START_REASON],
                    explanation=None,
                    readiness=readiness_from_score(score),
                    family=_job_family_name(job),
                    strategy="deterministic",
                    model_version=None,
                    propensity=None,
                )
            )

        items.sort(key=lambda item: (-item.match_score, str(item.job.id)))
        return RecommendationFeedResponse(
            items=items[:limit],
            total=len(items),
            profile_completeness_score=completeness,
            recommendation_type="cold_start",
            recommendation_strategy=COLD_STRATEGY_LABEL,
            strategy="deterministic",
            model_version=None,
            personalization_note=None,
        )

    @classmethod
    def _job_detail(cls, job: Job, relevance: float) -> JobDetailResponse:
        skills_list = [
            JobSkillRequirement(
                skill_name=js.skill.name,
                category=js.skill.category,
                is_required=js.is_required,
                importance_weight=float(js.importance_weight),
            )
            for js in (job.skills or [])
            if js.skill is not None and js.skill.name
        ]

        company = None
        try:
            if job.company is not None:
                company = CompanySummary.model_validate(job.company)
        except Exception:
            company = None
        if company is None:
            company = CompanySummary(
                id=job.company_id,
                name="Company",
                slug="company",
                location=None,
                website=None,
                is_verified=False,
            )

        try:
            applicants = len(job.applications) if job.applications is not None else 0
        except Exception:
            applicants = 0

        return JobDetailResponse(
            id=job.id,
            company_id=job.company_id,
            posted_by_user_id=job.posted_by_user_id,
            title=job.title,
            description=job.description,
            requirements=job.requirements,
            employment_type=job.employment_type,
            experience_level=job.experience_level,
            location=job.location,
            is_remote=job.is_remote,
            salary_min=job.salary_min,
            salary_max=job.salary_max,
            salary_currency=job.salary_currency,
            status=job.status,
            created_at=job.created_at,
            updated_at=job.updated_at,
            company=company,
            skills=skills_list,
            applicant_count=applicants,
            relevance_score=relevance,
        )

    @classmethod
    def compute_profile_completeness(cls, profile: Profile) -> float:
        points = 0.0
        max_points = 100.0

        if profile.first_name and profile.last_name:
            points += 15.0
        if profile.headline:
            points += 15.0
        if profile.bio and len(profile.bio) > 20:
            points += 15.0
        if profile.location:
            points += 10.0
        if profile.years_of_experience is not None:
            points += 10.0
        if profile.resume_url:
            points += 15.0
        skill_count = len(profile.skills or [])
        if skill_count >= 5:
            points += 20.0
        elif skill_count >= 1:
            points += 10.0

        return round(min(max_points, points), 1)
