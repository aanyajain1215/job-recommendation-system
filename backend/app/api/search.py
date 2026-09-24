"""Search autocomplete (plan §18): GET /search/skills?q=.

Skill autocomplete resolved **through the normalizer** — exact alias hits
("js" → JavaScript) rank first, then canonical substring matches.  Read-only:
no rows are created for unknown queries.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models.skill import Skill
from app.schemas.skill import SkillResponse
from app.services.skill_normalizer import build_db_normalizer

router = APIRouter(tags=["search"])


@router.get(
    "/search/skills",
    response_model=list[SkillResponse],
    summary="Alias-aware skill autocomplete through the normalizer",
)
def search_skills(
    db: Annotated[Session, Depends(get_db)],
    q: Annotated[str, Query(min_length=1, max_length=100)],
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> list[SkillResponse]:
    """§18: canonical-first autocomplete; unknown queries just no-op."""
    text = q.strip()
    normalizer = build_db_normalizer(db)

    canonical = text
    try:
        result = normalizer.normalize(text)
        canonical = getattr(result, "canonical", None) or text
    except Exception:  # pragma: no cover - defensive
        canonical = text

    exact = db.scalar(select(Skill).where(func.lower(Skill.name) == canonical.lower()))
    like_rows = db.scalars(
        select(Skill)
        .where(Skill.name.ilike(f"%{canonical}%"))
        .order_by(Skill.name.asc())
        .limit(limit)
    ).all()

    seen: set[str] = set()
    out: list[SkillResponse] = []
    if exact is not None:
        out.append(SkillResponse.model_validate(exact))
        seen.add(exact.name.lower())
    for row in like_rows:
        if row.name.lower() in seen:
            continue
        out.append(SkillResponse.model_validate(row))
        seen.add(row.name.lower())
        if len(out) >= limit:
            break
    return out
