"""Batch embedding backfill for jobs + profiles + skills (plan §4/§13).

Recomputes null-or-stale embedding vectors in batches using the configured
backend (MiniLM when importable, deterministic hashing fallback otherwise).
Vectors are invalidated on write (updated_at > embedding_updated_at) and
this script is the bulk recompute path; the API also fills lazily.
Skill vectors power family centroids / transfer similarity (plan §5/§11) —
Skill rows carry no updated_at, so they recompute whenever null.

Usage:
    cd backend
    python -m scripts.embed_backfill                # jobs + profiles + skills
    python -m scripts.embed_backfill --jobs-only
    python -m scripts.embed_backfill --profiles-only
    python -m scripts.embed_backfill --skills-only
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.db import SessionLocal
from app.models.job import Job
from app.models.profile import Profile
from app.models.skill import JobSkill, ProfileSkill, Skill
from app.services.embeddings import build_job_text, build_profile_text, get_embedder

BATCH_SIZE = 128


def _stale(obj) -> bool:
    if obj.embedding is None or obj.embedding_updated_at is None:
        return True
    return obj.updated_at is not None and obj.embedding_updated_at < obj.updated_at


def backfill_jobs(db, embedder) -> tuple[int, int]:
    jobs = db.scalars(
        select(Job).options(selectinload(Job.skills).selectinload(JobSkill.skill))
    ).all()
    stale = [job for job in jobs if _stale(job)]
    now = datetime.now(timezone.utc)
    for start in range(0, len(stale), BATCH_SIZE):
        chunk = stale[start : start + BATCH_SIZE]
        texts = [
            build_job_text(
                title=job.title,
                requirements=job.requirements,
                description=job.description,
                required_skills=[
                    js.skill.name
                    for js in (job.skills or [])
                    if js.skill is not None and js.skill.name and js.is_required
                ],
            )
            for job in chunk
        ]
        for job, vec in zip(chunk, embedder.encode(texts), strict=True):
            job.embedding = vec.tolist()
            job.embedding_updated_at = now
        db.commit()
        print(f"  jobs: {min(start + BATCH_SIZE, len(stale))}/{len(stale)}")
    return len(stale), len(jobs)


def backfill_profiles(db, embedder) -> tuple[int, int]:
    profiles = db.scalars(
        select(Profile).options(
            selectinload(Profile.skills).selectinload(ProfileSkill.skill),
            selectinload(Profile.target_family),
        )
    ).all()
    stale = [profile for profile in profiles if _stale(profile)]
    now = datetime.now(timezone.utc)
    for start in range(0, len(stale), BATCH_SIZE):
        chunk = stale[start : start + BATCH_SIZE]
        texts = [
            build_profile_text(
                headline=profile.headline,
                bio=profile.bio,
                skill_names=[
                    ps.skill.name
                    for ps in (profile.skills or [])
                    if ps.skill is not None and ps.skill.name
                ],
                target_family=(
                    profile.target_family.name
                    if profile.target_family is not None
                    else None
                ),
                project_blurb=None,
            )
            for profile in chunk
        ]
        for profile, vec in zip(chunk, embedder.encode(texts), strict=True):
            profile.embedding = vec.tolist()
            profile.embedding_updated_at = now
        db.commit()
        print(f"  profiles: {min(start + BATCH_SIZE, len(stale))}/{len(stale)}")
    return len(stale), len(profiles)


def backfill_skills(db, embedder) -> tuple[int, int]:
    skills = db.scalars(select(Skill)).all()
    stale = [s for s in skills if s.embedding is None or s.embedding_updated_at is None]
    now = datetime.now(timezone.utc)
    for start in range(0, len(stale), BATCH_SIZE):
        chunk = stale[start : start + BATCH_SIZE]
        texts = [
            f"{s.name} ({s.category})" if s.category else s.name
            for s in chunk
        ]
        for skill, vec in zip(chunk, embedder.encode(texts), strict=True):
            skill.embedding = vec.tolist()
            skill.embedding_updated_at = now
        db.commit()
        print(f"  skills: {min(start + BATCH_SIZE, len(stale))}/{len(stale)}")
    return len(stale), len(skills)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill job/profile/skill embeddings"
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--jobs-only", action="store_true")
    group.add_argument("--profiles-only", action="store_true")
    group.add_argument("--skills-only", action="store_true")
    args = parser.parse_args()

    embedder = get_embedder()
    print(f"Embedder backend: {embedder.backend}")

    db = SessionLocal()
    try:
        only = args.jobs_only or args.profiles_only or args.skills_only
        if not only or args.jobs_only:
            done, total = backfill_jobs(db, embedder)
            print(f"jobs: {done}/{total} embedded")
        if not only or args.profiles_only:
            done, total = backfill_profiles(db, embedder)
            print(f"profiles: {done}/{total} embedded")
        if not only or args.skills_only:
            done, total = backfill_skills(db, embedder)
            print(f"skills: {done}/{total} embedded")
        print("embed_backfill complete.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
