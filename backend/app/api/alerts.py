"""Saved-job alert settings, preview, and in-app notifications API."""

from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.db import get_db
from app.models.alerts import JobAlert, JobAlertItem, Notification
from app.models.profile import Profile
from app.models.user import User
from app.schemas.alerts import (
    AlertJobOut,
    AlertMatchOut,
    AlertPreviewOut,
    AlertSettingsOut,
    AlertSettingsUpdate,
    NotificationListOut,
    NotificationOut,
    NotificationReadAllOut,
    NotificationReadOut,
)
from app.services.job_alerts import find_matches, get_or_create_alert

router = APIRouter(prefix="/alerts", tags=["alerts"])
notifications_router = APIRouter(prefix="/notifications", tags=["notifications"])


def _require_profile(db: Session, user: User) -> Profile:
    profile = db.scalar(select(Profile).where(Profile.user_id == user.id))
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Complete your profile before using job alerts.",
        )
    return profile


@router.get("/settings", response_model=AlertSettingsOut)
def get_alert_settings(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> AlertSettingsOut:
    """Return job-alert settings, creating defaults on first visit."""
    profile = _require_profile(db, current_user)
    alert = get_or_create_alert(db, current_user.id, profile.id)
    db.commit()
    db.refresh(alert)
    return AlertSettingsOut.model_validate(alert)


@router.put("/settings", response_model=AlertSettingsOut)
def update_alert_settings(
    payload: AlertSettingsUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> AlertSettingsOut:
    """Update one or more alert preferences."""
    profile = _require_profile(db, current_user)
    alert = get_or_create_alert(db, current_user.id, profile.id)

    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        if value is not None:
            setattr(alert, field, value)
    if "enabled" in data and data["enabled"] is not None:
        alert.enabled = bool(data["enabled"])
    if "email_enabled" in data and data["email_enabled"] is not None:
        alert.email_enabled = bool(data["email_enabled"])
    alert.updated_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(alert)
    return AlertSettingsOut.model_validate(alert)


@router.get("/preview", response_model=AlertPreviewOut)
def preview_alert_matches(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    min_score: Annotated[float | None, Query(ge=0.0, le=100.0)] = None,
    limit: Annotated[int | None, Query(ge=1, le=20)] = None,
) -> AlertPreviewOut:
    """Dry-run the matcher against the user's saved jobs (no writes)."""
    profile = _require_profile(db, current_user)
    alert = get_or_create_alert(db, current_user.id, profile.id)
    now = datetime.now(timezone.utc)

    scan = find_matches(
        db,
        alert,
        since=None,
        limit=limit,
        min_score=min_score,
    )

    items: list[AlertMatchOut] = []
    for match in scan.items:
        job = match.job
        items.append(
            AlertMatchOut(
                job=AlertJobOut(
                    id=job.id,
                    title=job.title,
                    company_name=job.company.name if job.company is not None else None,
                    location=job.location,
                    is_remote=job.is_remote,
                    employment_type=job.employment_type.value
                    if job.employment_type
                    else None,
                    experience_level=job.experience_level.value
                    if job.experience_level
                    else None,
                    salary_min=job.salary_min,
                    salary_max=job.salary_max,
                    salary_currency=job.salary_currency,
                    created_at=job.created_at,
                ),
                score=match.score,
                seed_job_id=match.seed_job.id,
                seed_job_title=match.seed_job.title,
                reason=match.reason,
                matched_skills=match.matched_skills,
            )
        )

    return AlertPreviewOut(
        items=items,
        seeds_used=scan.seeds_used,
        candidates_scanned=scan.candidates_scanned,
        min_score=float(alert.min_score if min_score is None else min_score),
        generated_at=now,
    )


@router.delete("/history", status_code=status.HTTP_204_NO_CONTENT)
def clear_alert_history(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    """Forget which jobs were already alerted, so future runs can re-match."""
    db.execute(
        Notification.__table__.delete().where(Notification.user_id == current_user.id)
    )
    db.execute(
        JobAlertItem.__table__.delete().where(JobAlertItem.user_id == current_user.id)
    )
    alert = db.scalar(select(JobAlert).where(JobAlert.user_id == current_user.id))
    if alert is not None:
        alert.last_digest_at = None
    db.commit()


# ---------------------------------------------------------------------------
# In-app notifications
# ---------------------------------------------------------------------------

@notifications_router.get("", response_model=NotificationListOut)
def list_notifications(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    unread_only: Annotated[bool, Query()] = False,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> NotificationListOut:
    filters = [Notification.user_id == current_user.id]
    if unread_only:
        filters.append(Notification.read_at.is_(None))

    total = db.scalar(
        select(func.count()).select_from(Notification).where(*filters)
    ) or 0
    unread = db.scalar(
        select(func.count())
        .select_from(Notification)
        .where(Notification.user_id == current_user.id, Notification.read_at.is_(None))
    ) or 0

    rows = db.scalars(
        select(Notification)
        .where(*filters)
        .order_by(Notification.created_at.desc(), Notification.id)
        .limit(limit)
        .offset(offset)
    ).all()

    return NotificationListOut(
        items=[NotificationOut.model_validate(row) for row in rows],
        total=int(total),
        unread=int(unread),
    )


@notifications_router.get("/unread-count")
def unread_count(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, int]:
    """Cheap polling endpoint for the navbar badge."""
    count = db.scalar(
        select(func.count())
        .select_from(Notification)
        .where(Notification.user_id == current_user.id, Notification.read_at.is_(None))
    ) or 0
    return {"unread": int(count)}


@notifications_router.post("/{notification_id}/read", response_model=NotificationReadOut)
def mark_notification_read(
    notification_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> NotificationReadOut:
    notification = db.scalar(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.user_id == current_user.id,
        )
    )
    if notification is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found."
        )
    if notification.read_at is None:
        notification.read_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(notification)
    return NotificationReadOut(id=notification.id, read_at=notification.read_at)


@notifications_router.post("/read-all", response_model=NotificationReadAllOut)
def mark_all_notifications_read(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> NotificationReadAllOut:
    now = datetime.now(timezone.utc)
    result = db.execute(
        Notification.__table__.update()
        .where(
            Notification.user_id == current_user.id,
            Notification.read_at.is_(None),
        )
        .values(read_at=now)
    )
    db.commit()
    return NotificationReadAllOut(marked=int(result.rowcount or 0))
