from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SkillResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    category: str | None = None


class SkillCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    category: str | None = Field(default=None, max_length=100)
