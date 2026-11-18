"""Dev-only: load the 10 REAL CC0 audit profiles used by Phase 0.

Source: opensporks/resumes (CC0-1.0), 10 anonymised real resumes selected
across 10 categories.  The rows are committed at
``ml/data/external/audit_real_profiles_10.json`` with provenance metadata.

This script is NOT part of production startup.  It is idempotent: it removes
and recreates only the ``audit_livecareer_*@jobrec.local`` accounts.

Run from ``backend/``::

    python scripts/seed_audit_profiles.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from argon2 import PasswordHasher  # noqa: E402
from sqlalchemy import delete, select  # noqa: E402

from app.core.db import SessionLocal  # noqa: E402
from app.models.enums import (  # noqa: E402
    ProficiencyLevel,
    SkillSource,
    UserRole,
)
from app.models.job_family import JobFamily  # noqa: E402
from app.models.profile import Profile  # noqa: E402
from app.models.skill import ProfileSkill, Skill  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.embeddings import ensure_profile_embedding  # noqa: E402
from app.services.ingest import (  # noqa: E402
    assign_family,
    extract_skills,
    load_families,
    load_surface_pairs,
)

SOURCE = BACKEND / "ml" / "data" / "external" / "audit_real_profiles_10.json"
EMAIL_TMPL = "audit_livecareer_{idx:02d}@audit.jobrec.io"
DEV_PASSWORD = "AuditOnly123!"  # dev-only; never used in production config


def _years(text: str) -> float:
    hits = [int(m) for m in re.findall(r"(\d{1,2})\+?\s+years?", text.lower())]
    return float(min(max(hits), 40)) if hits else 5.0


def _headline(text: str) -> str:
    for line in text.splitlines():
        line = " ".join(line.split())
        if len(line) >= 4:
            return line[:255]
    return "REAL AUDIT PROFILE"


def main() -> int:
    rows = json.loads(SOURCE.read_text(encoding="utf-8-sig"))
    assert len(rows) == 10, f"expected 10 real profiles, got {len(rows)}"

    db = SessionLocal()
    try:
        emails = [EMAIL_TMPL.format(idx=i) for i in range(len(rows))]
        emails += [f"audit_livecareer_{i:02d}@jobrec.local" for i in range(len(rows))]
        db.execute(delete(User).where(User.email.in_(emails)))
        db.commit()

        all_skills = db.scalars(select(Skill)).all()
        # YAML aliases + the real DB taxonomy — the app's own surface scanner,
        # no new extraction logic.
        pairs = load_surface_pairs() + [(s.name.lower(), s.name) for s in all_skills]
        families = load_families()
        skill_by_name = {s.name.lower(): s.id for s in all_skills}
        family_by_name = {f.name: f.id for f in db.scalars(select(JobFamily)).all()}
        hasher = PasswordHasher()

        for idx, row in enumerate(rows):
            text = row["resume_text"]
            headline = _headline(text)
            years = _years(text)
            user = User(
                email=EMAIL_TMPL.format(idx=idx),
                hashed_password=hasher.hash(DEV_PASSWORD),
                role=UserRole.JOB_SEEKER,
                is_active=True,
                is_verified=True,
            )
            db.add(user)
            db.flush()

            profile = Profile(
                user_id=user.id,
                first_name="Audit",
                last_name=f"Real{idx:02d}",
                headline=headline,
                bio=(
                    "REAL-RESUME AUDIT PROFILE (not synthetic). "
                    f"dataset={row['dataset']} licence={row['licence']} "
                    f"source_id={row['source_id']} category={row['category']} "
                    f"url={row['source_url']}"
                ),
                location=None,  # never fabricate a location
                raw_resume_text=text,
                years_of_experience=years,
                parsed_resume_data={
                    "audit": True,
                    "synthetic": False,
                    "source_id": row["source_id"],
                    "category": row["category"],
                },
                target_job_family_id=None,
            )
            fam_name = assign_family(headline, families)
            if fam_name:
                profile.target_job_family_id = family_by_name.get(fam_name)
            db.add(profile)
            db.flush()

            for canonical, _required in extract_skills(headline, text, pairs):
                sid = skill_by_name.get(canonical.lower())
                if sid is None:
                    continue
                db.add(
                    ProfileSkill(
                        profile_id=profile.id,
                        skill_id=sid,
                        proficiency_level=(
                            ProficiencyLevel.ADVANCED if years >= 8 else ProficiencyLevel.INTERMEDIATE
                        ),
                        years_of_experience=years,
                        source=SkillSource.RESUME,
                    )
                )

            ensure_profile_embedding(profile)
            print(f"{row['category']:24s} skills_linked={len(profile.skills)} years={years:g}")

        db.commit()
        print("seeded 10 real CC0 audit profiles (dev-only)")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
