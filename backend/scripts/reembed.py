#!/usr/bin/env python
"""Safe re-embedding script with provenance tracking (Phase 1.3).

Rebuilds embeddings for profiles, jobs, and skills using the active embedder,
saving full provenance (backend, model, version, dimension, content hash).

Features:
- Dry-run mode (--dry-run)
- Bounded batches (--batch-size, default 64)
- Restartable and idempotent
- Streaming/chunked queries (no full-table loads into memory)
- Per-record error isolation (one bad row does not crash the run)
- Reports processed, skipped, failed, remaining counts

Usage:
    python -m scripts.reembed --target all
    python -m scripts.reembed --target jobs --batch-size 32
    python -m scripts.reembed --dry-run
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func, select

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core.db import SessionLocal
from app.models.job import Job
from app.models.profile import Profile
from app.models.skill import Skill
from app.services.embeddings import (
    build_job_text,
    build_profile_text,
    build_skill_text,
    compute_content_hash,
    get_embedder,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("reembed")


def reembed_profiles(db, embedder, batch_size: int = 64, force: bool = False, dry_run: bool = False) -> dict[str, int]:
    counts = {"total": 0, "processed": 0, "skipped": 0, "failed": 0, "remaining": 0}
    total = db.scalar(select(func.count(Profile.id))) or 0
    counts["total"] = total
    counts["remaining"] = total

    log.info("Scanning %d profiles...", total)
    offset = 0
    while offset < total:
        profiles = db.scalars(
            select(Profile).order_by(Profile.created_at).offset(offset).limit(batch_size)
        ).all()
        if not profiles:
            break

        for p in profiles:
            counts["remaining"] -= 1
            try:
                skill_names = [ps.skill.name for ps in (p.skills or []) if ps.skill and ps.skill.name]
                target_fam = p.target_family.name if p.target_family else None
                text = build_profile_text(p.headline, p.bio, skill_names, target_fam)
                chash = compute_content_hash(text)

                is_stale = (
                    force
                    or p.embedding is None
                    or p.embedding_updated_at is None
                    or getattr(p, "embedding_backend", None) != embedder.backend
                    or getattr(p, "embedding_model", None) != embedder.model_name
                    or getattr(p, "embedding_content_hash", None) != chash
                    or (p.updated_at is not None and p.embedding_updated_at < p.updated_at)
                )

                if not is_stale:
                    counts["skipped"] += 1
                    continue

                if dry_run:
                    counts["processed"] += 1
                    continue

                vec = embedder.encode_one(text)
                now = datetime.now(timezone.utc)
                p.embedding = vec
                p.embedding_backend = embedder.backend
                p.embedding_model = embedder.model_name
                p.embedding_version = embedder.version
                p.embedding_dimension = embedder.dimension
                p.embedding_content_hash = chash
                p.embedding_updated_at = now
                counts["processed"] += 1

            except Exception as exc:
                counts["failed"] += 1
                log.exception("Failed embedding profile %s: %s", p.id, exc)

        if not dry_run:
            db.commit()
        offset += batch_size

    return counts


def reembed_jobs(db, embedder, batch_size: int = 64, force: bool = False, dry_run: bool = False) -> dict[str, int]:
    counts = {"total": 0, "processed": 0, "skipped": 0, "failed": 0, "remaining": 0}
    total = db.scalar(select(func.count(Job.id))) or 0
    counts["total"] = total
    counts["remaining"] = total

    log.info("Scanning %d jobs...", total)
    offset = 0
    while offset < total:
        jobs = db.scalars(
            select(Job).order_by(Job.created_at).offset(offset).limit(batch_size)
        ).all()
        if not jobs:
            break

        stale_jobs = []
        for j in jobs:
            counts["remaining"] -= 1
            try:
                req_skills = [
                    js.skill.name
                    for js in (j.skills or [])
                    if js.skill and js.skill.name and js.is_required
                ]
                text = build_job_text(j.title, j.requirements, j.description, req_skills)
                chash = compute_content_hash(text)

                is_stale = (
                    force
                    or j.embedding is None
                    or j.embedding_updated_at is None
                    or getattr(j, "embedding_backend", None) != embedder.backend
                    or getattr(j, "embedding_model", None) != embedder.model_name
                    or getattr(j, "embedding_content_hash", None) != chash
                    or (j.updated_at is not None and j.embedding_updated_at < j.updated_at)
                )

                if not is_stale:
                    counts["skipped"] += 1
                    continue

                if dry_run:
                    counts["processed"] += 1
                    continue

                stale_jobs.append((j, text, chash))

            except Exception as exc:
                counts["failed"] += 1
                log.exception("Failed processing job %s: %s", j.id, exc)

        if stale_jobs and not dry_run:
            try:
                vecs = embedder.encode([item[1] for item in stale_jobs])
                now = datetime.now(timezone.utc)
                for (j, _, chash), vec in zip(stale_jobs, vecs, strict=True):
                    j.embedding = vec.tolist()
                    j.embedding_backend = embedder.backend
                    j.embedding_model = embedder.model_name
                    j.embedding_version = embedder.version
                    j.embedding_dimension = embedder.dimension
                    j.embedding_content_hash = chash
                    j.embedding_updated_at = now
                    counts["processed"] += 1
                db.commit()
            except Exception as exc:
                counts["failed"] += len(stale_jobs)
                log.exception("Failed batch embedding jobs: %s", exc)
                db.rollback()

        offset += batch_size

    return counts


def reembed_skills(db, embedder, batch_size: int = 128, force: bool = False, dry_run: bool = False) -> dict[str, int]:
    counts = {"total": 0, "processed": 0, "skipped": 0, "failed": 0, "remaining": 0}
    total = db.scalar(select(func.count(Skill.id))) or 0
    counts["total"] = total
    counts["remaining"] = total

    log.info("Scanning %d skills...", total)
    offset = 0
    while offset < total:
        skills = db.scalars(
            select(Skill).order_by(Skill.created_at).offset(offset).limit(batch_size)
        ).all()
        if not skills:
            break

        stale_skills = []
        for s in skills:
            counts["remaining"] -= 1
            try:
                text = build_skill_text(s.name, s.category)
                chash = compute_content_hash(text)

                is_stale = (
                    force
                    or s.embedding is None
                    or s.embedding_updated_at is None
                    or getattr(s, "embedding_backend", None) != embedder.backend
                    or getattr(s, "embedding_model", None) != embedder.model_name
                    or getattr(s, "embedding_content_hash", None) != chash
                )

                if not is_stale:
                    counts["skipped"] += 1
                    continue

                if dry_run:
                    counts["processed"] += 1
                    continue

                stale_skills.append((s, text, chash))

            except Exception as exc:
                counts["failed"] += 1
                log.exception("Failed processing skill %s: %s", s.id, exc)

        if stale_skills and not dry_run:
            try:
                vecs = embedder.encode([item[1] for item in stale_skills])
                now = datetime.now(timezone.utc)
                for (s, _, chash), vec in zip(stale_skills, vecs, strict=True):
                    s.embedding = vec.tolist()
                    s.embedding_backend = embedder.backend
                    s.embedding_model = embedder.model_name
                    s.embedding_version = embedder.version
                    s.embedding_dimension = embedder.dimension
                    s.embedding_content_hash = chash
                    s.embedding_updated_at = now
                    counts["processed"] += 1
                db.commit()
            except Exception as exc:
                counts["failed"] += len(stale_skills)
                log.exception("Failed batch embedding skills: %s", exc)
                db.rollback()

        offset += batch_size

    return counts


def main():
    parser = argparse.ArgumentParser(description="Rebuild embeddings with provenance.")
    parser.add_argument("--target", choices=["all", "jobs", "profiles", "skills"], default="all")
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--force", action="store_true", help="Re-embed even if fresh")
    parser.add_argument("--dry-run", action="store_true", help="Report counts without writing")
    args = parser.parse_args()

    embedder = get_embedder()
    log.info("Using embedder backend: %s (model=%s, dry_run=%s)", embedder.backend, embedder.model_name, args.dry_run)

    with SessionLocal() as db:
        if args.target in ("all", "profiles"):
            res = reembed_profiles(db, embedder, batch_size=args.batch_size, force=args.force, dry_run=args.dry_run)
            log.info("Profiles result: %s", res)
        if args.target in ("all", "jobs"):
            res = reembed_jobs(db, embedder, batch_size=args.batch_size, force=args.force, dry_run=args.dry_run)
            log.info("Jobs result: %s", res)
        if args.target in ("all", "skills"):
            res = reembed_skills(db, embedder, batch_size=args.batch_size, force=args.force, dry_run=args.dry_run)
            log.info("Skills result: %s", res)

    log.info("Re-embed complete.")


if __name__ == "__main__":
    main()

