"""Profile synchronization service (Phase 1.2).

Ensures that structured child tables (`education`, `experience`) serve as the
authoritative, queryable source of truth while maintaining backward-compatible
JSONB representations without drift or duplicates.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.profile import Profile
from app.models.profile_entities import Education, Experience

log = logging.getLogger(__name__)


def _norm_str(val: Any) -> str:
    return " ".join(str(val or "").strip().lower().split())


def sync_jsonb_to_structured(db: Session, profile: Profile) -> dict[str, int]:
    """Idempotently backfills profile JSONB education/work_experience into structured rows.

    Deterministic deduplication:
    - Education: (profile_id, lower(degree), lower(institution))
    - Experience: (profile_id, lower(title), lower(company))

    Returns:
        {"education_added": count, "experience_added": count}
    """
    stats = {"education_added": 0, "experience_added": 0}

    # 1. Backfill education
    if profile.education and isinstance(profile.education, list):
        existing_edu = db.scalars(
            select(Education).where(Education.profile_id == profile.id)
        ).all()
        existing_edu_keys = {
            (_norm_str(e.degree), _norm_str(e.institution)) for e in existing_edu
        }

        has_primary = any(e.is_primary for e in existing_edu)
        for item in profile.education:
            if not isinstance(item, dict):
                continue
            deg = item.get("degree") or item.get("degree_name")
            inst = item.get("institution") or item.get("school")
            key = (_norm_str(deg), _norm_str(inst))
            if not key[0] and not key[1]:
                continue
            if key not in existing_edu_keys:
                is_prim = bool(item.get("is_primary", False))
                if not has_primary and not existing_edu:
                    is_prim = True
                    has_primary = True

                row = Education(
                    profile_id=profile.id,
                    degree=str(deg).strip()[:200] if deg else None,
                    institution=str(inst).strip()[:200] if inst else None,
                    field_of_study=str(item.get("field_of_study") or item.get("major") or "").strip()[:200] or None,
                    grad_year=int(item["grad_year"]) if str(item.get("grad_year", "")).isdigit() else None,
                    is_primary=is_prim,
                )
                db.add(row)
                existing_edu_keys.add(key)
                stats["education_added"] += 1

    # 2. Backfill experience
    if profile.work_experience and isinstance(profile.work_experience, list):
        existing_exp = db.scalars(
            select(Experience).where(Experience.profile_id == profile.id)
        ).all()
        existing_exp_keys = {
            (_norm_str(e.title), _norm_str(e.company)) for e in existing_exp
        }

        for item in profile.work_experience:
            if not isinstance(item, dict):
                continue
            title = item.get("title") or item.get("role") or item.get("position")
            company = item.get("company") or item.get("employer") or item.get("organization")
            key = (_norm_str(title), _norm_str(company))
            if not key[0]:
                continue
            if key not in existing_exp_keys:
                skills_val = item.get("skills_used") or item.get("skills")
                if isinstance(skills_val, list):
                    skills_list = [str(s).strip() for s in skills_val if s and str(s).strip()]
                else:
                    skills_list = None

                row = Experience(
                    profile_id=profile.id,
                    title=str(title).strip()[:200],
                    company=str(company).strip()[:200] if company else None,
                    location=str(item.get("location") or "").strip()[:150] or None,
                    start_date=str(item.get("start_date") or "").strip()[:30] or None,
                    end_date=str(item.get("end_date") or "").strip()[:30] or None,
                    current=bool(item.get("current", False)),
                    description=str(item.get("description") or "").strip() or None,
                    skills_used=skills_list,
                )
                db.add(row)
                existing_exp_keys.add(key)
                stats["experience_added"] += 1

    return stats

