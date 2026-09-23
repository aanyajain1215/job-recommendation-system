from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.models import SystemHeartbeat

router = APIRouter(tags=["health"])


class LivenessResponse(BaseModel):
    status: str = Field(examples=["ok"])
    service: str
    environment: str


class ReadinessResponse(BaseModel):
    status: str = Field(examples=["ready"])
    service: str
    database: str = Field(examples=["connected"])
    postgres_version: str
    database_time: datetime
    heartbeat_id: UUID
    heartbeat_message: str
    heartbeat_recorded_at: datetime


@router.get("/health", response_model=LivenessResponse)
def liveness() -> LivenessResponse:
    settings = get_settings()
    return LivenessResponse(
        status="ok",
        service="jobrec-api",
        environment=settings.environment,
    )


@router.get("/health/ready", response_model=ReadinessResponse)
def readiness(db: Session = Depends(get_db)) -> ReadinessResponse:
    try:
        db_row = db.execute(text("SELECT version(), CURRENT_TIMESTAMP")).one()
        heartbeat = db.scalar(select(SystemHeartbeat).limit(1))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is not reachable",
        ) from exc

    if heartbeat is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="system_heartbeat row is missing; run database migrations",
        )

    return ReadinessResponse(
        status="ready",
        service="jobrec-api",
        database="connected",
        postgres_version=str(db_row[0]),
        database_time=db_row[1],
        heartbeat_id=heartbeat.id,
        heartbeat_message=heartbeat.message,
        heartbeat_recorded_at=heartbeat.recorded_at,
    )
