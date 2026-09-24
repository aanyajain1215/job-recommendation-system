"""Admin operations API (plan §21/§22, §18 admin surface).

Every route is gated behind ``require_roles(ADMIN)``:

- ``GET  /admin/skills``                 — skill inventory with usage counts
- ``POST /admin/skills/merge``           — transactional merge (demo §24.8)
- ``GET  /admin/jobs/duplicates``        — embedding cos ≥ .92 + title similarity
- ``GET  /admin/llm-usage``              — cost meter + per-route rollup (§22)
- ``GET  /admin/parse-failures``         — failed/stuck resume parses
- ``POST /admin/parse-failures/{id}/retry``
- ``GET  /admin/config``                 — scoring weights + LLM kill-switch state
- ``PUT  /admin/config``                 — weights validated Σ=1 on save (§7)
- ``GET  /admin/models``                 — trained-artifact registry (§6)

Data-integrity rules (§22): the merge runs in a single transaction;
``recommendations``/``skill_gaps`` JSONB snapshots are immutable audit rows
and are never rewritten.
"""

from __future__ import annotations

import logging
import math
from difflib import SequenceMatcher
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.api.profiles import UPLOAD_DIR, _run_resume_parse
from app.core.config import get_settings
from app.core.db import get_db
from app.models.career_path import CareerPathStep, LearningResource
from app.models.enums import UserRole
from app.models.feedback import SkillAffinity
from app.models.job import Job
from app.models.ops import LlmUsage, ModelRegistry
from app.models.profile_entities import Resume
from app.models.skill import JobSkill, ProfileSkill, Skill
from app.models.skill_graph import SkillAlias, SkillEdge
from app.models.user import User
from app.services import runtime_config

log = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])

AdminDep = Annotated[User, Depends(require_roles(UserRole.ADMIN))]
DbDep = Annotated[Session, Depends(get_db)]

# Rough $/1M-token list prices for the admin cost meter (§22) — estimates only.
MODEL_PRICING: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gemini-1.5-flash": (0.075, 0.30),
}

DUPLICATE_COS_THRESHOLD = 0.92
DUPLICATE_TITLE_MIN = 0.60
STUCK_PARSE_MINUTES = 15


class SkillMergeRequest(BaseModel):
    source_id: UUID = Field(description="Skill to absorb and remove")
    target_id: UUID = Field(description="Canonical skill that survives")


class ConfigUpdateRequest(BaseModel):
    weights: dict[str, float]


# ---------------------------------------------------------------------------
# Skills inventory + transactional merge
# ---------------------------------------------------------------------------


@router.get("/skills")
def list_skills(
    _: AdminDep,
    db: DbDep,
    q: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> dict[str, Any]:
    """Skill inventory with live usage counts — the merge picker's data."""
    profiles_cnt = (
        select(ProfileSkill.profile_id, ProfileSkill.skill_id)
        .where(ProfileSkill.skill_id == Skill.id)
        .subquery()
    )
    jobs_cnt = (
        select(JobSkill.job_id, JobSkill.skill_id)
        .where(JobSkill.skill_id == Skill.id)
        .subquery()
    )
    aliases_cnt = (
        select(SkillAlias.id, SkillAlias.skill_id)
        .where(SkillAlias.skill_id == Skill.id)
        .subquery()
    )

    stmt = (
        select(
            Skill,
            func.count(func.distinct(profiles_cnt.c.profile_id)),
            func.count(func.distinct(jobs_cnt.c.job_id)),
            func.count(func.distinct(aliases_cnt.c.id)),
        )
        .select_from(Skill)
        .outerjoin(profiles_cnt, profiles_cnt.c.skill_id == Skill.id)
        .outerjoin(jobs_cnt, jobs_cnt.c.skill_id == Skill.id)
        .outerjoin(aliases_cnt, aliases_cnt.c.skill_id == Skill.id)
        .group_by(Skill.id)
        .order_by(
            (
                func.count(func.distinct(profiles_cnt.c.profile_id))
                + func.count(func.distinct(jobs_cnt.c.job_id))
            ).desc(),
            Skill.name,
        )
        .limit(limit)
    )
    if q:
        stmt = stmt.where(Skill.name.ilike(f"%{q.strip()}%"))

    rows = db.execute(stmt).all()
    total = db.scalar(select(func.count(Skill.id))) or 0
    return {
        "total_skills": int(total),
        "items": [
            {
                "id": str(skill.id),
                "name": skill.name,
                "category": skill.category,
                "profiles": int(profile_count),
                "jobs": int(job_count),
                "aliases": int(alias_count),
                "has_embedding": skill.embedding is not None,
            }
            for skill, profile_count, job_count, alias_count in rows
        ],
    }


def _merge_profile_skills(db: Session, source_id: UUID, target_id: UUID) -> dict[str, int]:
    existing = set(
        db.scalars(
            select(ProfileSkill.profile_id).where(ProfileSkill.skill_id == target_id)
        ).all()
    )
    moved = deduped = 0
    for row in db.scalars(
        select(ProfileSkill).where(ProfileSkill.skill_id == source_id)
    ).all():
        if row.profile_id in existing:
            db.delete(row)
            deduped += 1
        else:
            row.skill_id = target_id
            moved += 1
    return {"moved": moved, "deduped": deduped}


def _merge_job_skills(db: Session, source_id: UUID, target_id: UUID) -> dict[str, int]:
    existing = set(
        db.scalars(
            select(JobSkill.job_id).where(JobSkill.skill_id == target_id)
        ).all()
    )
    moved = deduped = 0
    for row in db.scalars(
        select(JobSkill).where(JobSkill.skill_id == source_id)
    ).all():
        if row.job_id in existing:
            db.delete(row)
            deduped += 1
        else:
            row.skill_id = target_id
            moved += 1
    return {"moved": moved, "deduped": deduped}


def _merge_aliases(db: Session, source: Skill, target: Skill) -> dict[str, int]:
    """Aliases are globally unique — colliding rows are dropped, rest re-pointed."""
    taken = {
        (a.alias or "").strip().lower()
        for a in db.scalars(select(SkillAlias)).all()
        if a.skill_id != source.id
    }
    moved = dropped = 0
    for alias in db.scalars(
        select(SkillAlias).where(SkillAlias.skill_id == source.id)
    ).all():
        key = (alias.alias or "").strip().lower()
        if key in taken:
            db.delete(alias)
            dropped += 1
        else:
            alias.skill_id = target.id
            taken.add(key)
            moved += 1

    # Preserve the absorbed name as an alias so old resumes/jobs still resolve.
    source_key = source.name.strip().lower()
    if source_key not in taken:
        db.add(
            SkillAlias(
                alias=source.name,
                skill_id=target.id,
                confidence=1.0,
                source="admin",
            )
        )
        moved += 1
    return {"moved": moved, "dropped": dropped}


def _merge_edges(db: Session, source_id: UUID, target_id: UUID) -> dict[str, int]:
    """Rebuild source edges onto the target, skipping duplicates/self-loops."""
    src_edges = db.scalars(
        select(SkillEdge).where(
            (SkillEdge.from_skill_id == source_id)
            | (SkillEdge.to_skill_id == source_id)
        )
    ).all()
    if not src_edges:
        return {"moved": 0, "skipped": 0}

    payload = [
        (
            target_id if e.from_skill_id == source_id else e.from_skill_id,
            target_id if e.to_skill_id == source_id else e.to_skill_id,
            e.edge_type,
            e.weight,
            e.source,
            e.approved,
        )
        for e in src_edges
    ]
    for edge in src_edges:
        db.delete(edge)
    db.flush()

    existing = set(
        db.execute(
            select(SkillEdge.from_skill_id, SkillEdge.to_skill_id, SkillEdge.edge_type)
        ).all()
    )

    moved = skipped = 0
    for frm, to, edge_type, weight, edge_source, approved in payload:
        if frm == to or (frm, to, edge_type) in existing:
            skipped += 1
            continue
        db.add(
            SkillEdge(
                from_skill_id=frm,
                to_skill_id=to,
                edge_type=edge_type,
                weight=weight,
                source=edge_source,
                approved=approved,
            )
        )
        existing.add((frm, to, edge_type))
        moved += 1
    return {"moved": moved, "skipped": skipped}


def _merge_affinities(db: Session, source_id: UUID, target_id: UUID) -> dict[str, int]:
    existing = set(
        db.scalars(
            select(SkillAffinity.profile_id).where(SkillAffinity.skill_id == target_id)
        ).all()
    )
    moved = deduped = 0
    for row in db.scalars(
        select(SkillAffinity).where(SkillAffinity.skill_id == source_id)
    ).all():
        if row.profile_id in existing:
            db.delete(row)
            deduped += 1
        else:
            row.skill_id = target_id
            moved += 1
    return {"moved": moved, "deduped": deduped}


@router.post("/skills/merge")
def merge_skills(
    payload: SkillMergeRequest,
    _: AdminDep,
    db: DbDep,
) -> dict[str, Any]:
    """Plan §24.8 demo: merge `Node`/`NodeJS` — every profile, job, alias,
    edge, affinity and learning resource is re-pointed in ONE transaction,
    then the target embedding is refreshed.  JSONB audit snapshots stay
    immutable (§22)."""
    if payload.source_id == payload.target_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Source and target must be different skills.",
        )
    source = db.get(Skill, payload.source_id)
    target = db.get(Skill, payload.target_id)
    if source is None or target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Both source and target skills must exist.",
        )

    report: dict[str, Any] = {
        "source": {"id": str(source.id), "name": source.name},
        "target": {"id": str(target.id), "name": target.name},
    }

    try:
        report["profile_skills"] = _merge_profile_skills(db, source.id, target.id)
        report["job_skills"] = _merge_job_skills(db, source.id, target.id)
        report["skill_aliases"] = _merge_aliases(db, source, target)
        report["skill_edges"] = _merge_edges(db, source.id, target.id)
        report["skill_affinities"] = _merge_affinities(db, source.id, target.id)

        # Learning resources (CASCADE would drop them) + path steps (SET NULL).
        for model in (LearningResource, CareerPathStep):
            for row in db.scalars(
                select(model).where(model.skill_id == source.id)
            ).all():
                row.skill_id = target.id
            report[model.__tablename__] = "re-pointed"

        # Flush all pending re-points FIRST: with autoflush=False a single
        # flush would order the skills DELETE before the profile_skills /
        # job_skills UPDATEs (FK dependency), and SQL ON DELETE CASCADE
        # would wipe rows we just re-pointed to the target.
        db.flush()
        # Absorbed skill row — ORM cascades clean up any leftover links.
        db.delete(source)
        db.flush()

        # Refresh the surviving embedding (demo §24.8: "embeddings refreshed").
        embedding_refreshed = False
        try:
            from app.services.embeddings import get_embedder

            target.embedding = get_embedder().encode_one(target.name)
            embedding_refreshed = True
        except Exception:  # pragma: no cover - embedder optional at ops time
            log.exception("Embedding refresh failed for skill %s", target.id)
        report["embedding_refreshed"] = embedding_refreshed

        db.commit()
    except Exception:
        db.rollback()
        log.exception("Skill merge failed; transaction rolled back")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Merge failed and was rolled back — no partial changes.",
        )

    return {"status": "merged", **report}


# ---------------------------------------------------------------------------
# Duplicate job detection (detection ships; auto-merge is a cut line §24)
# ---------------------------------------------------------------------------


@router.get("/jobs/duplicates")
def job_duplicates(
    _: AdminDep,
    db: DbDep,
    threshold: Annotated[float, Query(ge=0.5, le=1.0)] = DUPLICATE_COS_THRESHOLD,
    title_min: Annotated[float, Query(ge=0.0, le=1.0)] = DUPLICATE_TITLE_MIN,
) -> dict[str, Any]:
    """Candidate duplicate postings: embedding cosine ≥ threshold AND title
    similarity ≥ title_min.  Read-only — merging is a human decision (§24)."""
    rows = db.execute(
        select(Job.id, Job.title, Job.location, Job.created_at, Job.embedding)
        .where(Job.embedding.isnot(None))
        .order_by(Job.created_at)
    ).all()

    vectors: list[tuple[Any, list[float]]] = []
    for job in rows:
        try:
            vec = [float(x) for x in (job.embedding or [])]
        except TypeError:  # numpy array from pgvector
            vec = [float(x) for x in list(job.embedding or [])]
        if vec:
            vectors.append((job, vec))

    norms = [
        math.sqrt(sum(v * v for v in vec)) or 1.0 for _, vec in vectors
    ]
    skill_counts = dict(
        db.execute(
            select(JobSkill.job_id, func.count()).group_by(JobSkill.job_id)
        ).all()
    )

    pairs: list[dict[str, Any]] = []
    for i in range(len(vectors)):
        job_a, vec_a = vectors[i]
        title_a = (job_a.title or "").strip().lower()
        for j in range(i + 1, len(vectors)):
            job_b, vec_b = vectors[j]
            cos = sum(x * y for x, y in zip(vec_a, vec_b)) / (
                norms[i] * norms[j]
            )
            if cos < threshold:
                continue
            title_b = (job_b.title or "").strip().lower()
            title_sim = SequenceMatcher(None, title_a, title_b).ratio()
            if title_sim < title_min:
                continue

            # Survivor: more linked skills, then the older posting, then id.
            count_a = skill_counts.get(job_a.id, 0)
            count_b = skill_counts.get(job_b.id, 0)
            if count_a != count_b:
                survivor, retired = job_a, job_b
            else:
                survivor, retired = (
                    (job_a, job_b)
                    if (job_a.created_at, str(job_a.id))
                    <= (job_b.created_at, str(job_b.id))
                    else (job_b, job_a)
                )
            pairs.append(
                {
                    "cosine": round(cos, 4),
                    "title_similarity": round(title_sim, 4),
                    "job_a": {
                        "id": str(job_a.id),
                        "title": job_a.title,
                        "location": job_a.location,
                        "skills": count_a,
                    },
                    "job_b": {
                        "id": str(job_b.id),
                        "title": job_b.title,
                        "location": job_b.location,
                        "skills": count_b,
                    },
                    "suggested_survivor_id": str(survivor.id),
                    "suggested_retire_id": str(retired.id),
                }
            )

    pairs.sort(key=lambda p: -p["cosine"])
    return {
        "threshold": threshold,
        "title_similarity_min": title_min,
        "jobs_examined": len(vectors),
        "pairs": pairs,
    }


# ---------------------------------------------------------------------------
# LLM usage cost meter (§22)
# ---------------------------------------------------------------------------


@router.get("/llm-usage")
def llm_usage(_: AdminDep, db: DbDep) -> dict[str, Any]:
    totals = db.execute(
        select(
            func.count(LlmUsage.id),
            func.coalesce(func.sum(LlmUsage.prompt_tokens), 0),
            func.coalesce(func.sum(LlmUsage.completion_tokens), 0),
            func.coalesce(
                func.sum(case((LlmUsage.cached == True, 1), else_=0)), 0  # noqa: E712
            ),
            func.coalesce(
                func.sum(case((LlmUsage.flagged == True, 1), else_=0)), 0  # noqa: E712
            ),
            func.avg(LlmUsage.latency_ms),
        )
    ).one()

    by_route = db.execute(
        select(
            LlmUsage.route,
            func.count(LlmUsage.id),
            func.coalesce(func.sum(LlmUsage.prompt_tokens), 0),
            func.coalesce(func.sum(LlmUsage.completion_tokens), 0),
            func.avg(LlmUsage.latency_ms),
            func.coalesce(
                func.sum(case((LlmUsage.flagged == True, 1), else_=0)), 0  # noqa: E712
            ),
        )
        .group_by(LlmUsage.route)
        .order_by(func.count(LlmUsage.id).desc())
    ).all()

    by_model = db.execute(
        select(
            LlmUsage.provider,
            LlmUsage.model,
            func.count(LlmUsage.id),
            func.coalesce(func.sum(LlmUsage.prompt_tokens), 0),
            func.coalesce(func.sum(LlmUsage.completion_tokens), 0),
        )
        .group_by(LlmUsage.provider, LlmUsage.model)
        .order_by(func.count(LlmUsage.id).desc())
    ).all()

    # Rough cost estimate (§22 cost meter) — unknown models report null.
    estimated_cost = 0.0
    cost_known = True
    for _provider, model, _count, prompt_tokens, completion_tokens in by_model:
        pricing = MODEL_PRICING.get(model)
        if pricing is None:
            cost_known = False
            continue
        in_price, out_price = pricing
        estimated_cost += (
            float(prompt_tokens) * in_price + float(completion_tokens) * out_price
        ) / 1_000_000

    recent = db.scalars(
        select(LlmUsage).order_by(LlmUsage.created_at.desc()).limit(25)
    ).all()

    settings = get_settings()
    return {
        "totals": {
            "calls": int(totals[0] or 0),
            "prompt_tokens": int(totals[1] or 0),
            "completion_tokens": int(totals[2] or 0),
            "cache_hits": int(totals[3] or 0),
            "flagged": int(totals[4] or 0),
            "avg_latency_ms": round(float(totals[5] or 0), 1),
            "estimated_cost_usd": round(estimated_cost, 6) if cost_known else None,
        },
        "by_route": [
            {
                "route": route,
                "calls": int(count),
                "prompt_tokens": int(pt),
                "completion_tokens": int(ct),
                "avg_latency_ms": round(float(avg or 0), 1),
                "flagged": int(flagged),
            }
            for route, count, pt, ct, avg, flagged in by_route
        ],
        "by_model": [
            {
                "provider": provider,
                "model": model,
                "calls": int(count),
                "prompt_tokens": int(pt),
                "completion_tokens": int(ct),
                "estimated_cost_usd": (
                    round(
                        (float(pt) * MODEL_PRICING[model][0]
                         + float(ct) * MODEL_PRICING[model][1])
                        / 1_000_000,
                        6,
                    )
                    if model in MODEL_PRICING
                    else None
                ),
            }
            for provider, model, count, pt, ct in by_model
        ],
        "recent": [
            {
                "id": str(row.id),
                "route": row.route,
                "provider": row.provider,
                "model": row.model,
                "prompt_tokens": row.prompt_tokens,
                "completion_tokens": row.completion_tokens,
                "latency_ms": row.latency_ms,
                "cached": row.cached,
                "flagged": row.flagged,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in recent
        ],
        "llm_enabled": settings.llm_enabled,
    }


# ---------------------------------------------------------------------------
# Parse failures + retry
# ---------------------------------------------------------------------------


@router.get("/parse-failures")
def parse_failures(_: AdminDep, db: DbDep) -> dict[str, Any]:
    """Failed resume parses, plus rows stuck in 'parsing' beyond the SLA."""
    rows = db.scalars(
        select(Resume).where(Resume.parse_status.in_(["failed", "parsing"]))
    ).all()

    items: list[dict[str, Any]] = []
    for row in rows:
        stuck = False
        if row.parse_status == "parsing" and row.created_at is not None:
            from datetime import datetime, timezone

            age_min = (
                datetime.now(timezone.utc) - row.created_at
            ).total_seconds() / 60.0
            stuck = age_min > STUCK_PARSE_MINUTES
        if row.parse_status == "parsing" and not stuck:
            continue  # still within its normal window
        items.append(
            {
                "id": str(row.id),
                "profile_id": str(row.profile_id),
                "original_filename": row.original_filename,
                "parse_status": row.parse_status,
                "parser_used": row.parser_used,
                "stuck": stuck,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
        )
    return {"items": items, "stuck_after_minutes": STUCK_PARSE_MINUTES}


@router.post("/parse-failures/{resume_id}/retry")
def retry_parse(
    resume_id: UUID,
    _: AdminDep,
    db: DbDep,
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    """Re-run the deterministic/LLM parse pipeline for a failed resume row."""
    resume = db.get(Resume, resume_id)
    if resume is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Resume row not found.",
        )

    stored = Path(resume.file_path or "")
    target_path = UPLOAD_DIR / stored.name
    if not target_path.exists():
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Stored file no longer exists on disk; ask the user to re-upload.",
        )

    content = target_path.read_bytes()
    resume.parse_status = "parsing"
    db.commit()

    background_tasks.add_task(
        _run_resume_parse,
        profile_id=resume.profile_id,
        file_bytes=content,
        extension=stored.suffix.lower(),
        stored_filename=stored.name,
    )
    return {
        "status": "retrying",
        "resume_id": str(resume.id),
        "profile_id": str(resume.profile_id),
    }


# ---------------------------------------------------------------------------
# Config (weights Σ=1) + model registry
# ---------------------------------------------------------------------------


@router.get("/config")
def get_config(_: AdminDep, db: DbDep) -> dict[str, Any]:
    settings = get_settings()
    weights = runtime_config.get_scoring_weights(db)
    source = (
        "system_config"
        if runtime_config.has_custom_weights(db)
        else "defaults"
    )
    return {
        "weights": [
            {
                "component": item["component"],
                "label": item["label"],
                "weight": round(weights[item["component"]], 4),
                "default": item["default"],
            }
            for item in runtime_config.component_catalog()
        ],
        "source": source,
        "sum": round(sum(weights.values()), 6),
        "llm": {
            "enabled": settings.llm_enabled,
            "provider": settings.llm_provider,
            "model": settings.llm_model,
            "has_api_key": bool(
                settings.openai_api_key or settings.gemini_api_key
            ),
            "kill_switch": "LLM_ENABLED=false",
        },
        "m4": {
            "learning_rate": 0.15,
            "bounds": [0.5, 2.0],
            "shrinkage_k": 10,
        },
    }


@router.put("/config")
def put_config(
    payload: ConfigUpdateRequest,
    admin: AdminDep,
    db: DbDep,
) -> dict[str, Any]:
    """Persist global scoring weights — validated Σ=1, all 8 components (§7)."""
    try:
        saved = runtime_config.set_scoring_weights(
            db, payload.weights, updated_by_user_id=admin.id
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )
    db.commit()
    return {
        "status": "saved",
        "source": "system_config",
        "weights": {k: round(v, 4) for k, v in saved.items()},
        "sum": round(sum(saved.values()), 6),
    }


@router.get("/models")
def list_models(_: AdminDep, db: DbDep) -> dict[str, Any]:
    """Trained-artifact registry with metrics + on-disk existence check (§6)."""
    rows = db.scalars(
        select(ModelRegistry)
        .order_by(ModelRegistry.name, ModelRegistry.trained_at.desc())
    ).all()
    items: list[dict[str, Any]] = []
    for row in rows:
        exists = False
        try:
            exists = Path(row.artifact_path).exists()
        except (OSError, ValueError):
            exists = False
        items.append(
            {
                "id": str(row.id),
                "name": row.name,
                "version": row.version,
                "artifact_path": row.artifact_path,
                "artifact_exists": exists,
                "metrics": row.metrics or {},
                "active": row.active,
                "trained_at": (
                    row.trained_at.isoformat() if row.trained_at else None
                ),
            }
        )
    return {"items": items, "total": len(items)}
