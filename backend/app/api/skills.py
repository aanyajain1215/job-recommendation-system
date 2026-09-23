from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models.skill import Skill
from app.schemas.skill import SkillCreateRequest, SkillResponse

router = APIRouter(prefix="/skills", tags=["skills"])


@router.get("", response_model=list[SkillResponse])
def list_skills(
    db: Annotated[Session, Depends(get_db)],
    search: str | None = None,
    category: str | None = None,
    limit: int = 50,
) -> list[SkillResponse]:
    """List or autocomplete skills from the canonical taxonomy."""
    query = select(Skill)

    if search:
        query = query.where(Skill.name.ilike(f"%{search.strip()}%"))
    if category:
        query = query.where(func.lower(Skill.category) == category.strip().lower())

    query = query.order_by(Skill.name.asc()).limit(limit)
    skills = db.scalars(query).all()
    return [SkillResponse.model_validate(s) for s in skills]


@router.post("", response_model=SkillResponse, status_code=status.HTTP_201_CREATED)
def create_skill(
    payload: SkillCreateRequest,
    db: Annotated[Session, Depends(get_db)],
) -> SkillResponse:
    """Add a new skill to the taxonomy if not already existing."""
    normalized_name = payload.name.strip()
    existing = db.scalar(select(Skill).where(Skill.name.ilike(normalized_name)))
    if existing:
        return SkillResponse.model_validate(existing)

    skill = Skill(
        name=normalized_name,
        category=payload.category.strip().lower() if payload.category else None,
    )
    db.add(skill)
    db.commit()
    db.refresh(skill)
    return SkillResponse.model_validate(skill)
