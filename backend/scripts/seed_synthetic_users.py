#!/usr/bin/env python
"""Synthetic seeker bootstrap (plan §6 M2 / §16).

Creates `--count` (default 200) seeker accounts (`synth####@jobrec.test`)
with profiles, profile skills, and graded interactions produced by the
pluggable ground-truth preference function (`ml/ground_truth.py`).  Every
generated row carries `metadata.synthetic = true` and all timestamps are
staggered across the past 60 days so the temporal split in
`ml/build_datasets.py` is meaningful.

    python scripts/seed_synthetic_users.py            # create/refresh
    python scripts/seed_synthetic_users.py --delete   # purge everything

Idempotency: `run` first removes any previous synthetic users, then seeds.
"""

from __future__ import annotations

import argparse
import json
import random
import secrets
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

EMAIL_DOMAIN = "jobrec.test"

FIRSTS = ["Aarav", "Bianca", "Chen", "Dmitri", "Elena", "Farah", "Grace",
          "Hiro", "Imani", "Jonas", "Kaia", "Luca", "Mira", "Noor", "Omar"]
LASTS = ["Iyer", "Novak", "Silva", "Weber", "Okafor", "Kim", "Rossi",
         "Haddad", "Lindqvist", "Moreau"]

CITIES = ["Bengaluru, India", "Remote", "Austin, United States",
          "London, United Kingdom", "Berlin, Germany", "Toronto, Canada"]

INTEREST_KEYWORDS = {
    "backend": ["backend", "apis", "microservices"],
    "frontend": ["frontend", "ui", "design systems"],
    "devops": ["devops", "platform", "reliability"],
    "data": ["analytics", "dashboards", "data pipelines"],
    "ml": ["machine learning", "nlp", "models"],
    "fullstack": ["full stack", "product engineering", "web"],
}


def _read_resumes() -> list[dict]:
    path = BACKEND / "ml" / "data" / "golden" / "resumes.jsonl"
    if not path.exists():
        from scripts.synthesize_corpus import build_all  # noqa: PLC0415

        build_all()
    rows = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            rows.append(json.loads(line))
    return rows


def delete_synthetic() -> int:
    """Purge all seeded synthetic users and their dependent rows."""
    from sqlalchemy import delete, select  # noqa: PLC0415

    from app.core.db import SessionLocal  # noqa: PLC0415
    from app.models.application import Application  # noqa: PLC0415
    from app.models.feedback import Feedback, SkillAffinity  # noqa: PLC0415
    from app.models.interaction import Interaction  # noqa: PLC0415
    from app.models.profile import Profile  # noqa: PLC0415
    from app.models.user import User  # noqa: PLC0415

    db = SessionLocal()
    try:
        users = list(
            db.scalars(
                select(User).where(User.email.like(f"synth%@{EMAIL_DOMAIN}"))
            ).all()
        )
        user_ids = [u.id for u in users]
        if not user_ids:
            print("no synthetic users found")
            return 0

        profile_rows = list(
            db.execute(select(Profile.id, Profile.user_id).where(Profile.user_id.in_(user_ids))).all()
        )
        profile_ids = [r[0] for r in profile_rows]

        db.execute(delete(Interaction).where(Interaction.user_id.in_(user_ids)))
        db.execute(delete(Application).where(Application.user_id.in_(user_ids)))
        if profile_ids:
            db.execute(delete(Feedback).where(Feedback.profile_id.in_(profile_ids)))
            db.execute(delete(SkillAffinity).where(SkillAffinity.profile_id.in_(profile_ids)))
            db.execute(delete(Profile).where(Profile.id.in_(profile_ids)))
        for user in users:
            db.delete(user)
        db.commit()
        print(f"deleted {len(users)} synthetic users")
        return len(users)
    finally:
        db.close()


def run(count: int = 200, seed: int = 1729) -> dict:
    from argon2 import PasswordHasher  # noqa: PLC0415
    from sqlalchemy import select  # noqa: PLC0415
    from sqlalchemy.orm import selectinload  # noqa: PLC0415

    from app.core.config import get_settings  # noqa: PLC0415
    from app.core.db import SessionLocal  # noqa: PLC0415
    from app.models.application import Application  # noqa: PLC0415
    from app.models.enums import (  # noqa: PLC0415
        ApplicationStatus,
        InteractionType,
        JobStatus,
        UserRole,
        WorkMode,
    )
    from app.models.feedback import Feedback, FeedbackReason  # noqa: PLC0415
    from app.models.interaction import Interaction  # noqa: PLC0415
    from app.models.job import Job  # noqa: PLC0415
    from app.models.job_family import JobFamily  # noqa: PLC0415
    from app.models.profile import Profile  # noqa: PLC0415
    from app.models.skill import JobSkill, ProfileSkill, Skill, SkillSource  # noqa: PLC0415
    from app.models.skill_graph import SkillAlias  # noqa: PLC0415
    from app.models.user import User  # noqa: PLC0415
    from app.services.recommender import _ProfileContext  # noqa: PLC0415
    from app.services.scoring import score_pair  # noqa: PLC0415

    from ml.ground_truth import (  # noqa: PLC0415
        ARCHETYPES,
        LABEL_APPLY,
        LABEL_NEGATIVE,
        ground_truth_grade,
        sample_label,
    )

    delete_synthetic()

    rng = random.Random(seed)
    settings = get_settings()
    seed_rng = random.Random(settings.synthetic_seed)

    resumes = _read_resumes()
    ph = PasswordHasher()

    db = SessionLocal()
    stats = {"users": 0, "profiles": 0, "skills": 0, "interactions": 0,
             "feedback": 0, "applications": 0}
    try:
        families = {
            f.name.lower().strip(): f.id for f in db.scalars(select(JobFamily)).all()
        }
        skill_lookup: dict[str, object] = {}
        for skill in db.scalars(select(Skill)).all():
            skill_lookup[skill.name.lower().strip()] = skill.id
        for alias in db.scalars(select(SkillAlias)).all():
            skill_lookup.setdefault(alias.alias.lower().strip(), alias.skill_id)

        jobs = list(
            db.scalars(
                select(Job)
                .where(Job.status == JobStatus.PUBLISHED)
                .options(
                    selectinload(Job.skills).selectinload(JobSkill.skill),
                    selectinload(Job.family),
                    selectinload(Job.company),
                    selectinload(Job.applications),
                )
            ).all()
        )
        if not jobs:
            raise SystemExit("no published jobs — run scripts/seed_canonical.py first")

        now = datetime.now(timezone.utc)
        hash_cache: str | None = None

        for i in range(count):
            resume = resumes[i % len(resumes)]
            arch_name = resume["archetype"]
            prefs = ARCHETYPES[arch_name]

            if hash_cache is None:
                hash_cache = ph.hash(secrets.token_urlsafe(24))

            user = User(
                email=f"synth{i:04d}@{EMAIL_DOMAIN}",
                hashed_password=hash_cache,
                role=UserRole.JOB_SEEKER,
                is_active=True,
                is_verified=False,
            )
            db.add(user)
            db.flush()

            first = FIRSTS[i % len(FIRSTS)]
            last = LASTS[(i * 7) % len(LASTS)]
            remote_lean = prefs.remote_lean
            work_mode = (
                WorkMode.REMOTE
                if remote_lean >= 0.5
                else WorkMode.HYBRID if remote_lean >= 0 else WorkMode.ONSITE
            )
            salary_lo = 60000 + (i % 8) * 5000
            salary_hi = salary_lo + rng.randint(20, 50) * 1000
            family_id = families.get(prefs.target_family.lower().strip())
            if family_id is None:
                # loose fallback: first family whose name shares a word
                for name, fid in families.items():
                    if name.split()[0] in prefs.target_family.lower():
                        family_id = fid
                        break

            profile = Profile(
                user_id=user.id,
                first_name=first,
                last_name=last,
                headline=f"{resume['title']} · {prefs.target_family} focus",
                bio=resume["text"][:400],
                location=CITIES[i % len(CITIES)],
                years_of_experience=float(rng.randint(1, 9)),
                expected_salary_min=salary_lo,
                expected_salary_max=salary_hi,
                expected_salary_currency="USD",
                target_job_family_id=family_id,
                preferred_work_mode=work_mode,
                career_interests=INTEREST_KEYWORDS.get(arch_name, [arch_name]),
                preferred_locations=["Remote"]
                if work_mode == WorkMode.REMOTE
                else [CITIES[i % len(CITIES)]],
            )
            db.add(profile)
            db.flush()
            stats["profiles"] += 1

            from app.models.enums import ProficiencyLevel  # noqa: PLC0415

            levels = [ProficiencyLevel.INTERMEDIATE, ProficiencyLevel.ADVANCED,
                      ProficiencyLevel.EXPERT]
            for skill_name in resume["expected"]["skills"]:
                skill_id = skill_lookup.get(skill_name.lower().strip())
                if skill_id is None:
                    continue
                db.add(ProfileSkill(
                    profile_id=profile.id,
                    skill_id=skill_id,
                    proficiency_level=rng.choice(levels),
                    years_of_experience=float(rng.randint(1, 9)),
                    source=SkillSource.MANUAL,
                ))
                stats["skills"] += 1

            ctx = _ProfileContext(profile)
            profile_day = rng.randrange(60)

            for job in jobs:
                inputs = ctx.inputs_for(job)
                result = score_pair(inputs)
                grade = ground_truth_grade(inputs, result, prefs, seed_rng)
                label = sample_label(grade, seed_rng)
                event = {
                    LABEL_NEGATIVE: InteractionType.DISMISS,
                    1: InteractionType.VIEW,
                    2: InteractionType.CLICK,
                    4: InteractionType.SAVE,
                    LABEL_APPLY: InteractionType.APPLY,
                }[label]
                when = now - timedelta(
                    days=profile_day,
                    hours=rng.randint(0, 23),
                    minutes=rng.randint(0, 59),
                )
                db.add(Interaction(
                    user_id=user.id,
                    job_id=job.id,
                    event_type=event,
                    metadata_={
                        "synthetic": True,
                        "grade": round(grade, 2),
                        "label": label,
                        "propensity": 1.0,
                        "archetype": arch_name,
                    },
                    created_at=when,
                ))
                stats["interactions"] += 1

                if label >= LABEL_APPLY and rng.random() < 0.5:
                    db.add(Application(
                        job_id=job.id,
                        user_id=user.id,
                        profile_id=profile.id,
                        status=ApplicationStatus.APPLIED,
                        applied_at=when,
                    ))
                    stats["applications"] += 1

                if rng.random() < 0.30:
                    if label == LABEL_NEGATIVE:
                        reason = rng.choice([
                            FeedbackReason.NOT_INTERESTED,
                            FeedbackReason.SALARY_ISSUE,
                            FeedbackReason.LOCATION_ISSUE,
                            FeedbackReason.TOO_DIFFICULT,
                            FeedbackReason.NOT_RELEVANT,
                        ])
                    elif label >= 4:
                        reason = FeedbackReason.RELEVANT
                    else:
                        reason = FeedbackReason.NOT_RELEVANT
                    db.add(Feedback(
                        profile_id=profile.id,
                        job_id=job.id,
                        reason=reason,
                        note=None,
                        created_at=when,
                    ))
                    stats["feedback"] += 1

            stats["users"] += 1
            if i % 25 == 24:
                db.commit()

        db.commit()
    finally:
        db.close()

    stats["seed"] = seed
    print(json.dumps(stats, indent=2))
    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed/delete synthetic seekers")
    parser.add_argument("--count", type=int, default=200)
    parser.add_argument("--seed", type=int, default=1729)
    parser.add_argument("--delete", action="store_true",
                        help="purge synthetic users and exit")
    args = parser.parse_args(argv)

    if args.delete:
        delete_synthetic()
        return 0
    run(args.count, args.seed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
