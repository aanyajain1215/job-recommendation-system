"""Skill disparity across *sets* of jobs (search, AI search, feed, direction).

Per-card chips (``gap_preview``) answer "what am I missing for this job?".
This module answers the two questions a seeker actually acts on:

1. **Result-set summary** — "across these 20 results, Docker is required by
   12 and missing from your profile".  Pure aggregation over the per-card
   matched / missing / transferable classes the deterministic scorer already
   produced, so the banner can never disagree with the cards.
2. **Direction gap** — for each target role/domain the seeker typed in the
   career-direction form (role/domain switchers), retrieve the jobs that
   represent that role (platform FTS ∪ embedding KNN, plus live Adzuna when
   configured), aggregate the skills those jobs demand, and classify each
   against the seeker's profile: have / transferable / missing.  Readiness
   is demand-weighted coverage — have = 1, transferable = 0.5, missing = 0.

No LLM is involved: every number is a count or a ratio of counts.
"""

from __future__ import annotations

import logging
from collections import Counter
from typing import Any, Iterable, Sequence
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session, selectinload

from app.models.enums import JobStatus
from app.models.job import Job
from app.models.profile import Profile
from app.models.skill import JobSkill
from app.schemas.skill_gap import (
    DirectionGap,
    DirectionGapResponse,
    SkillDemand,
    SkillGapSummary,
)
from app.services.gap_preview import seeker_skill_map, skill_detail_for
from app.services.scoring import JobSkillReq
from app.services.skill_graph import SkillGraph, load_seed_graph

log = logging.getLogger(__name__)

TOP_N = 6
MAX_TARGETS = 3
PLATFORM_JOBS_PER_TARGET = 30
LIVE_JOBS_PER_TARGET = 20
MIN_SHARE = 0.10          # a skill must appear in >= 10% of a target's jobs
RRF_K = 60


# ---------------------------------------------------------------------------
# 1. Result-set summary
# ---------------------------------------------------------------------------

def _demands(counter: Counter[str], display: dict[str, str], n: int, status: str) -> list[SkillDemand]:
    ordered = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
    return [
        SkillDemand(skill=display[key], jobs=count, share=round(count / n, 3), status=status)  # type: ignore[arg-type]
        for key, count in ordered[:TOP_N]
    ]


def summarize_items(items: Iterable[Any]) -> SkillGapSummary | None:
    """Aggregate per-card gap classes into one result-set summary.

    Accepts anything with ``matched_skills`` / ``missing_skills`` /
    ``transferable_skills`` / ``skill_match_score`` attributes (search cards
    and feed items both qualify).  Items with no skill annotation are not
    counted; returns None when nothing was annotated (anonymous viewer, empty
    profile, or jobs without listed skills).
    """
    missing: Counter[str] = Counter()
    transferable: Counter[str] = Counter()
    matched: Counter[str] = Counter()
    display: dict[str, str] = {}
    scores: list[float] = []
    analyzed = 0

    for item in items:
        m = list(getattr(item, "matched_skills", None) or [])
        miss = list(getattr(item, "missing_skills", None) or [])
        tr = list(getattr(item, "transferable_skills", None) or [])
        score = getattr(item, "skill_match_score", None)
        if not (m or miss or tr) and score is None:
            continue
        analyzed += 1
        if score is not None:
            scores.append(float(score))
        for bucket, names in ((matched, m), (missing, miss), (transferable, tr)):
            for name in {str(x).strip() for x in names if str(x).strip()}:
                key = name.lower()
                display.setdefault(key, name)
                bucket[key] += 1

    if analyzed == 0:
        return None

    top_missing = _demands(missing, display, analyzed, "missing")
    summary = SkillGapSummary(
        jobs_analyzed=analyzed,
        avg_skill_match=round(sum(scores) / len(scores), 1) if scores else None,
        top_missing=top_missing,
        top_transferable=_demands(transferable, display, analyzed, "transferable"),
        top_matched=_demands(matched, display, analyzed, "have"),
    )
    summary.headline = _headline(summary)
    return summary


def _headline(summary: SkillGapSummary) -> str:
    n = summary.jobs_analyzed
    noun = "result" if n == 1 else "results"
    if summary.top_missing:
        top = summary.top_missing[0]
        line = f"{top.skill} is required by {top.jobs} of these {n} {noun} and missing from your profile"
        if len(summary.top_missing) > 1:
            second = summary.top_missing[1]
            line += f"; {second.skill} by {second.jobs}"
        return line + "."
    return f"You cover the required skills of all {n} analysed {noun}."


# ---------------------------------------------------------------------------
# 2. Direction gap (career switchers)
# ---------------------------------------------------------------------------

def _platform_jobs_for(db: Session, target: str, limit: int) -> list[Job]:
    """Published platform jobs representing ``target``: FTS ∪ KNN via RRF."""
    legs: list[list[UUID]] = []
    try:
        rows = db.execute(
            text(
                "SELECT id FROM jobs WHERE status = :status "
                "AND search_vector @@ websearch_to_tsquery('english', :q) "
                "ORDER BY ts_rank_cd(search_vector, websearch_to_tsquery('english', :q)) DESC, id "
                "LIMIT :lim"
            ),
            {"status": JobStatus.PUBLISHED.name, "q": target, "lim": limit},
        ).all()
        legs.append([r[0] for r in rows])
    except Exception:  # noqa: BLE001 - FTS leg optional (e.g. sqlite test DB)
        db.rollback()
        log.debug("direction gap: FTS leg failed for %r", target, exc_info=True)

    try:
        from app.services.embeddings import get_embedder

        vec = get_embedder().encode_one(f"{target} {target}")
        rows = db.execute(
            select(Job.id)
            .where(Job.status == JobStatus.PUBLISHED, Job.embedding.is_not(None))
            .order_by(Job.embedding.cosine_distance(vec), Job.id)
            .limit(limit)
        ).all()
        legs.append([r[0] for r in rows])
    except Exception:  # noqa: BLE001 - KNN leg optional
        db.rollback()
        log.debug("direction gap: KNN leg failed for %r", target, exc_info=True)

    scores: dict[UUID, float] = {}
    for leg in legs:
        for rank, job_id in enumerate(leg, start=1):
            scores[job_id] = scores.get(job_id, 0.0) + 1.0 / (RRF_K + rank)
    ids = sorted(scores, key=lambda j: (-scores[j], str(j)))[:limit]
    if not ids:
        return []
    jobs = db.scalars(
        select(Job)
        .options(selectinload(Job.skills).selectinload(JobSkill.skill), selectinload(Job.company))
        .where(Job.id.in_(ids))
    ).all()
    order = {job_id: i for i, job_id in enumerate(ids)}
    return sorted(jobs, key=lambda j: order.get(j.id, 0))


def _requirements_of(job: Job) -> list[JobSkillReq]:
    return [
        JobSkillReq(
            name=js.skill.name,
            category=js.skill.category,
            is_required=bool(js.is_required),
            importance_weight=float(js.importance_weight or 1.0),
        )
        for js in (job.skills or [])
        if js.skill is not None and js.skill.name
    ]


def _live_postings_for(target: str, limit: int) -> list[dict]:
    try:
        from app.services import live_jobs

        postings, _total = live_jobs.search_postings(target, page=1, page_size=limit)
        return list(postings or [])[:limit]
    except Exception:  # noqa: BLE001 - no keys / provider down → platform only
        log.debug("direction gap: live leg unavailable for %r", target, exc_info=True)
        return []


def _targets_of(profile: Profile) -> list[tuple[str, str]]:
    targets: list[tuple[str, str]] = []
    seen: set[str] = set()
    for raw in profile.career_interests or []:
        name = str(raw or "").strip()
        if name and name.lower() not in seen:
            seen.add(name.lower())
            targets.append((name, "role"))
    family = getattr(profile, "target_family", None)
    if family is not None and family.name and family.name.lower() not in seen:
        targets.append((family.name, "family"))
    return targets[:MAX_TARGETS]


def gap_for_requirements(
    target: str,
    kind: str,
    job_requirements: Sequence[tuple[dict[str, str | None], list[JobSkillReq]]],
    seeker_skills: dict[str, tuple],
    *,
    graph: SkillGraph,
    sources: list[str],
) -> DirectionGap:
    """Pure aggregation: (job meta, requirements) pairs → one DirectionGap."""
    demand: Counter[str] = Counter()
    display: dict[str, str] = {}
    status: dict[str, str] = {}
    analyzed = 0
    samples: list[dict[str, str | None]] = []

    for meta, reqs in job_requirements:
        if not reqs:
            continue
        analyzed += 1
        if len(samples) < 5:
            samples.append(meta)
        detail = skill_detail_for(reqs, seeker_skills, graph=graph) if seeker_skills else None
        have = {s.lower() for s in (detail.matched if detail else [])}
        trans = {s.lower() for s in (detail.transferable if detail else [])}
        for req in {r.name.strip(): r for r in reqs if r.name.strip()}.values():
            key = req.name.lower().strip()
            display.setdefault(key, req.name.strip())
            demand[key] += 1
            if key in have or key in seeker_skills:
                status[key] = "have"
            elif key in trans and status.get(key) != "have":
                status[key] = "transferable"
            else:
                status.setdefault(key, "missing")

    if analyzed == 0:
        return DirectionGap(
            target=target,
            kind=kind,  # type: ignore[arg-type]
            sources=sources,
            note="No postings with listed skills were found for this target yet.",
        )

    skills = [
        SkillDemand(
            skill=display[key],
            jobs=count,
            share=round(count / analyzed, 3),
            status=status.get(key, "missing"),  # type: ignore[arg-type]
        )
        for key, count in sorted(demand.items(), key=lambda kv: (-kv[1], kv[0]))
        if count / analyzed >= MIN_SHARE or count >= 2
    ][:15]

    credit = {"have": 1.0, "transferable": 0.5, "missing": 0.0}
    total = sum(s.share for s in skills)
    readiness = (
        round(100.0 * sum(s.share * credit[s.status] for s in skills) / total, 1)
        if total > 0
        else None
    )
    top_missing = [s for s in skills if s.status == "missing"][:TOP_N]
    note = None
    if top_missing:
        names = ", ".join(s.skill for s in top_missing[:3])
        note = f"Most-demanded gaps for {target}: {names}."
    elif skills:
        note = f"You already cover the core skills {target} roles ask for."

    return DirectionGap(
        target=target,
        kind=kind,  # type: ignore[arg-type]
        jobs_analyzed=analyzed,
        sources=sources,
        readiness=readiness,
        skills=skills,
        top_missing=top_missing,
        sample_jobs=samples,
        note=note,
    )


def direction_gaps(db: Session, profile: Profile, *, include_live: bool = True) -> DirectionGapResponse:
    """Direction-gap report for every target role/family on the profile."""
    targets = _targets_of(profile)
    seeker_skills = seeker_skill_map(profile)
    if not targets:
        return DirectionGapResponse(
            seeker_skill_count=len(seeker_skills),
            message="Add target roles or a target role family in Career Direction to see what they demand.",
        )

    graph = load_seed_graph()
    out: list[DirectionGap] = []
    for target, kind in targets:
        pairs: list[tuple[dict[str, str | None], list[JobSkillReq]]] = []
        sources: list[str] = []

        platform = _platform_jobs_for(db, target, PLATFORM_JOBS_PER_TARGET)
        if platform:
            sources.append("platform")
        for job in platform:
            pairs.append(
                (
                    {
                        "id": str(job.id),
                        "title": job.title,
                        "company": job.company.name if job.company is not None else None,
                        "source": getattr(job, "source", None) or "native",
                    },
                    _requirements_of(job),
                )
            )

        if include_live:
            live = _live_postings_for(target, LIVE_JOBS_PER_TARGET)
            if live:
                sources.append("live")
            for posting in live:
                reqs = [
                    JobSkillReq(name=name, is_required=bool(required))
                    for name, required in posting.get("skills") or []
                    if name
                ]
                pairs.append(
                    (
                        {
                            "id": None,
                            "title": posting.get("title"),
                            "company": posting.get("company"),
                            "source": "adzuna",
                            "url": posting.get("url") or None,
                        },
                        reqs,
                    )
                )

        out.append(
            gap_for_requirements(target, kind, pairs, seeker_skills, graph=graph, sources=sources)
        )

    return DirectionGapResponse(targets=out, seeker_skill_count=len(seeker_skills))
