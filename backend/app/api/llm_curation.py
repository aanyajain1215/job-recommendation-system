"""Admin endpoints for LLM-assisted curation (P3, P10)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.deps import get_current_admin_user
from app.models.user import User
from app.services.llm_curation import propose_skill_aliases, propose_skill_edges

router = APIRouter(prefix="/admin/curation", tags=["admin"])


class SkillProposalRequest(BaseModel):
    skills: list[str] = Field(default_factory=list)


class EdgeProposalRequest(BaseModel):
    from_skill: str
    to_skill: str
    context: str = ""


@router.post("/skills/propose")
def propose_skills(
    payload: SkillProposalRequest,
    _: Annotated[User, Depends(get_current_admin_user)],
):
    return {"proposals": propose_skill_aliases(payload.skills)}


@router.post("/edges/propose")
def propose_edges(
    payload: EdgeProposalRequest,
    _: Annotated[User, Depends(get_current_admin_user)],
):
    return {
        "proposals": propose_skill_edges(payload.from_skill, payload.to_skill, context=payload.context),
        "note": "Proposals are unapproved suggestions; review before persisting as skill_edges.",
    }
