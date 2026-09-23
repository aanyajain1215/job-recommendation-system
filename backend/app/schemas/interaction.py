from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.enums import InteractionType


class InteractionCreate(BaseModel):
    """Payload for logging a single user–job interaction event."""

    user_id: UUID = Field(..., description="ID of the user performing the action")
    job_id: UUID = Field(..., description="ID of the job involved")
    event_type: InteractionType = Field(..., description="Interaction event type")
    metadata: dict[str, Any] | None = Field(
        None,
        description=(
            "Optional context JSON, e.g. {'source': 'feed', 'match_score': 71, "
            "'position': 3}"
        ),
    )


class InteractionResponse(BaseModel):
    """Persisted interaction record returned to callers."""

    id: UUID
    user_id: UUID
    job_id: UUID
    event_type: InteractionType
    metadata: dict[str, Any] | None
    created_at: datetime

    model_config = {"from_attributes": True}
