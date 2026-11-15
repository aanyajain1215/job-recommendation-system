"""Admin trust & safety + employer oversight surface.

This is deliberately separate from the employer console: admins do not manage
postings day-to-day. They monitor the two-sided marketplace, review flags and
act on suspicious behaviour.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.core.db import get_db
from app.models.application import Application
from app.models.company import Company
from app.models.enums import (
    ApplicationStatus,
    FlagSeverity,
    FlagStatus,
    FlagTargetType,
    JobStatus,
    UserRole,
)
from app.models.job import Job
from app.models.moderation import ModerationFlag
from app.models.skill import JobSkill
from app.models.user import User
from app.services.moderation import (
    SUSPICIOUS_EMPLOYER_THRESHOLD,
    SUSPICIOUS_JOB_THRESHOLD,
    employer_signals,
    job_signals,
)

router = APIRouter(prefix="/admin", tags=["admin"])

AdminDep = Annotated[User, Depends(require_roles(UserRole.ADMIN))]
DbDep = Annotated[Session, Depends(get_db)]


class EmployerVerifyRequest(BaseModel):
    is_verified: bool


class FlagCreateRequest(BaseModel):
    target_type: FlagTargetType
    target_id: UUID
    reason: str = Field(min_length=3, max_length=160)
    severity: FlagSeverity = FlagSeverity.MEDIUM
    details: str | None = Field(default=None, max_length=4000)


class FlagUpdateRequest(BaseModel):
    status: FlagStatus
    resolution_note: str | None = Field(default=None, max_length=4000)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _flag_dict(flag: ModerationFlag, emails: dict[UUID, str]) -> dict[str, Any]:
    return {
        "id": str(flag.id),
        "target_type": flag.target_type.value,
        "target_id": str(flag.target_id),
        "target_label": flag.target_label,
        "reason": flag.reason,
        "details": flag.details,
        "severity": flag.severity.value,
        "status": flag.status.value,
        "created_at": _iso(flag.created_at),
        "resolved_at": _iso(flag.resolved_at),
        "resolution_note": flag.resolution_note,
        "created_by": emails.get(flag.created_by_user_id) if flag.created_by_user_id else None,
        "resolved_by": emails.get(flag.resolved_by_user_id) if flag.resolved_by_user_id else None,
    }


def _flag_emails(db: Session, flags: list[ModerationFlag]) -> dict[UUID, str]:
    user_ids = {
        uid
        for flag in flags
        for uid in (flag.created_by_user_id, flag.resolved_by_user_id)
        if uid is not None
    }
    if not user_ids:
        return {}
    return dict(
        db.execute(select(User.id, User.email).where(User.id.in_(user_ids))).all()
    )


def _open_flag_counts(
    db: Session, target_type: FlagTargetType, target_ids: list[UUID]
) -> dict[UUID, int]:
    if not target_ids:
        return {}
    return dict(
        db.execute(
            select(ModerationFlag.target_id, func.count(ModerationFlag.id))
            .where(
                ModerationFlag.target_type == target_type,
                ModerationFlag.target_id.in_(target_ids),
                ModerationFlag.status == FlagStatus.OPEN,
            )
            .group_by(ModerationFlag.target_id)
        ).all()
    )


def _company_aggregates(
    db: Session, company_ids: list[UUID]
) -> dict[UUID, dict[str, int]]:
    if not company_ids:
        return {}
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    rows = db.execute(
        select(
            Job.company_id,
            func.count(Job.id),
            func.coalesce(
                func.sum(case((Job.status == JobStatus.PUBLISHED, 1), else_=0)), 0
            ),
            func.coalesce(
                func.sum(case((Job.created_at >= week_ago, 1), else_=0)), 0
            ),
            func.coalesce(
                func.sum(
                    case((func.lower(func.coalesce(Job.source, "")) == "native", 1), else_=0)
                ),
                0,
            ),
        )
        .where(Job.company_id.in_(company_ids))
        .group_by(Job.company_id)
    ).all()
    aggregates = {
        company_id: {
            "jobs_total": int(total),
            "published_jobs": int(published),
            "jobs_last_7d": int(recent),
            "native_jobs": int(native),
            "applications": 0,
            "hires": 0,
            "flagged_jobs": 0,
        }
        for company_id, total, published, recent, native in rows
    }
    for company_id in company_ids:
        aggregates.setdefault(
            company_id,
            {
                "jobs_total": 0,
                "published_jobs": 0,
                "jobs_last_7d": 0,
                "native_jobs": 0,
                "applications": 0,
                "hires": 0,
                "flagged_jobs": 0,
            },
        )

    for company_id, count in db.execute(
        select(Job.company_id, func.count(Application.id))
        .join(Application, Application.job_id == Job.id)
        .where(Job.company_id.in_(company_ids))
        .group_by(Job.company_id)
    ).all():
        aggregates[company_id]["applications"] = int(count)

    for company_id, count in db.execute(
        select(Job.company_id, func.count(Application.id))
        .join(Application, Application.job_id == Job.id)
        .where(
            Job.company_id.in_(company_ids),
            Application.status == ApplicationStatus.HIRED,
        )
        .group_by(Job.company_id)
    ).all():
        aggregates[company_id]["hires"] = int(count)

    for company_id, count in db.execute(
        select(Job.company_id, func.count(ModerationFlag.id))
        .join(
            ModerationFlag,
            and_(
                ModerationFlag.target_type == FlagTargetType.JOB,
                ModerationFlag.target_id == Job.id,
            ),
        )
        .where(
            Job.company_id.in_(company_ids),
            ModerationFlag.status == FlagStatus.OPEN,
        )
        .group_by(Job.company_id)
    ).all():
        aggregates[company_id]["flagged_jobs"] = int(count)

    return aggregates


def _owner_company_counts(db: Session, owner_ids: list[UUID]) -> dict[UUID, int]:
    if not owner_ids:
        return {}
    return dict(
        db.execute(
            select(Company.created_by_user_id, func.count(Company.id))
            .where(Company.created_by_user_id.in_(owner_ids))
            .group_by(Company.created_by_user_id)
        ).all()
    )


# ---------------------------------------------------------------------------
# Employer oversight
# ---------------------------------------------------------------------------


@router.get("/employers")
def list_employers(
    _: AdminDep,
    db: DbDep,
    q: Annotated[str | None, Query(max_length=200)] = None,
    verified: Annotated[bool | None, Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> dict[str, Any]:
    """Company/employer directory with posting, hiring and flag aggregates."""
    conditions = []
    if q:
        needle = f"%{q.strip()}%"
        conditions.append(or_(Company.name.ilike(needle), User.email.ilike(needle)))
    if verified is not None:
        conditions.append(Company.is_verified == verified)

    base = (
        select(Company, User)
        .join(User, User.id == Company.created_by_user_id)
        .where(*conditions)
    )
    total = int(
        db.scalar(
            select(func.count(Company.id))
            .join(User, User.id == Company.created_by_user_id)
            .where(*conditions)
        )
        or 0
    )
    rows = db.execute(
        base.order_by(Company.created_at.desc(), Company.id)
        .offset((page - 1) * limit)
        .limit(limit)
    ).all()

    company_ids = [company.id for company, _owner in rows]
    owner_ids = [owner.id for _company, owner in rows]
    aggregates = _company_aggregates(db, company_ids)
    owner_counts = _owner_company_counts(db, owner_ids)
    company_flags = _open_flag_counts(db, FlagTargetType.COMPANY, company_ids)

    items = []
    for company, owner in rows:
        stats = aggregates[company.id]
        score, reasons = employer_signals(
            company,
            owner=owner,
            published_jobs=stats["published_jobs"],
            application_count=stats["applications"],
            flagged_jobs=stats["flagged_jobs"],
            open_flags=int(company_flags.get(company.id, 0)),
            jobs_last_7d=stats["jobs_last_7d"],
            owner_company_count=owner_counts.get(owner.id, 1),
            native_jobs=stats["native_jobs"],
        )
        items.append(
            {
                "id": str(company.id),
                "name": company.name,
                "slug": company.slug,
                "industry": company.industry,
                "location": company.location,
                "website": company.website,
                "is_verified": company.is_verified,
                "created_at": _iso(company.created_at),
                "owner": {
                    "id": str(owner.id),
                    "email": owner.email,
                    "is_active": owner.is_active,
                    "is_verified": owner.is_verified,
                    "last_active_at": _iso(owner.last_active_at),
                },
                "postings": {
                    "total": stats["jobs_total"],
                    "published": stats["published_jobs"],
                    "last_7d": stats["jobs_last_7d"],
                },
                "applications": stats["applications"],
                "hires": stats["hires"],
                "open_flags": int(company_flags.get(company.id, 0)),
                "flagged_jobs": stats["flagged_jobs"],
                "risk_score": score,
                "risk_reasons": reasons,
            }
        )

    return {
        "items": items,
        "total": total,
        "page": page,
        "limit": limit,
        "total_pages": max(1, math.ceil(total / limit)),
    }


@router.patch("/employers/{company_id}")
def update_employer(
    company_id: UUID,
    payload: EmployerVerifyRequest,
    _: AdminDep,
    db: DbDep,
) -> dict[str, Any]:
    """Verify or un-verify a company (manual KYC step)."""
    company = db.get(Company, company_id)
    if company is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Company not found."
        )
    company.is_verified = payload.is_verified
    company.updated_at = datetime.now(timezone.utc)
    db.commit()
    return {
        "status": "updated",
        "company": {"id": str(company.id), "is_verified": company.is_verified},
    }


# ---------------------------------------------------------------------------
# Moderation flags
# ---------------------------------------------------------------------------


@router.get("/moderation/flags")
def list_flags(
    _: AdminDep,
    db: DbDep,
    flag_status: Annotated[FlagStatus | None, Query(alias="status")] = None,
    target_type: Annotated[FlagTargetType | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> dict[str, Any]:
    """Flag queue. Defaults to every status so history stays visible."""
    conditions = []
    if flag_status is not None:
        conditions.append(ModerationFlag.status == flag_status)
    if target_type is not None:
        conditions.append(ModerationFlag.target_type == target_type)

    flags = list(
        db.scalars(
            select(ModerationFlag)
            .where(*conditions)
            .order_by(ModerationFlag.created_at.desc())
            .limit(limit)
        ).all()
    )
    emails = _flag_emails(db, flags)
    counts = {
        value.value: 0 for value in FlagStatus
    }
    for value, count in db.execute(
        select(ModerationFlag.status, func.count(ModerationFlag.id)).group_by(
            ModerationFlag.status
        )
    ).all():
        counts[value.value] = int(count)
    return {
        "items": [_flag_dict(flag, emails) for flag in flags],
        "counts": counts,
        "total": sum(counts.values()),
    }


def _resolve_target(
    db: Session, target_type: FlagTargetType, target_id: UUID
) -> tuple[Any, str]:
    if target_type == FlagTargetType.JOB:
        target = db.get(Job, target_id)
        label = target.title if target else None
    elif target_type == FlagTargetType.COMPANY:
        target = db.get(Company, target_id)
        label = target.name if target else None
    else:
        target = db.get(User, target_id)
        label = target.email if target else None

    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{target_type.value.title()} not found.",
        )
    return target, label or str(target_id)


@router.post("/moderation/flags", status_code=status.HTTP_201_CREATED)
def create_flag(
    payload: FlagCreateRequest,
    admin: AdminDep,
    db: DbDep,
) -> dict[str, Any]:
    """Raise a trust & safety flag against a job, company or user."""
    _target, label = _resolve_target(db, payload.target_type, payload.target_id)

    flag = ModerationFlag(
        target_type=payload.target_type,
        target_id=payload.target_id,
        target_label=label,
        reason=payload.reason.strip(),
        details=(payload.details or "").strip() or None,
        severity=payload.severity,
        status=FlagStatus.OPEN,
        created_by_user_id=admin.id,
    )
    db.add(flag)
    db.commit()
    db.refresh(flag)
    return {
        "status": "created",
        "flag": _flag_dict(flag, {admin.id: admin.email}),
    }


@router.patch("/moderation/flags/{flag_id}")
def update_flag(
    flag_id: UUID,
    payload: FlagUpdateRequest,
    admin: AdminDep,
    db: DbDep,
) -> dict[str, Any]:
    """Resolve, dismiss or re-open a flag."""
    flag = db.get(ModerationFlag, flag_id)
    if flag is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Flag not found."
        )

    flag.status = payload.status
    if payload.status == FlagStatus.OPEN:
        flag.resolved_by_user_id = None
        flag.resolved_at = None
        flag.resolution_note = None
    else:
        flag.resolved_by_user_id = admin.id
        flag.resolved_at = datetime.now(timezone.utc)
        flag.resolution_note = (payload.resolution_note or "").strip() or None
    db.commit()
    db.refresh(flag)
    return {
        "status": "updated",
        "flag": _flag_dict(flag, {admin.id: admin.email}),
    }


# ---------------------------------------------------------------------------
# Suspicious postings / employers (heuristic triage, not auto-takedown)
# ---------------------------------------------------------------------------


@router.get("/moderation/suspicious-jobs")
def suspicious_jobs(
    _: AdminDep,
    db: DbDep,
    min_score: Annotated[int, Query(ge=1, le=20)] = SUSPICIOUS_JOB_THRESHOLD,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> dict[str, Any]:
    """Postings ranked by explainable risk signals (native rules + scam text)."""
    rows = db.execute(
        select(Job, Company, User)
        .join(Company, Company.id == Job.company_id)
        .join(User, User.id == Job.posted_by_user_id)
        .order_by(Job.created_at.desc())
        .limit(500)
    ).all()

    job_ids = [job.id for job, _company, _owner in rows]
    skill_counts = (
        dict(
            db.execute(
                select(JobSkill.job_id, func.count())
                .where(JobSkill.job_id.in_(job_ids))
                .group_by(JobSkill.job_id)
            ).all()
        )
        if job_ids
        else {}
    )
    application_counts = (
        dict(
            db.execute(
                select(Application.job_id, func.count(Application.id))
                .where(Application.job_id.in_(job_ids))
                .group_by(Application.job_id)
            ).all()
        )
        if job_ids
        else {}
    )
    flag_counts = _open_flag_counts(db, FlagTargetType.JOB, job_ids)

    items = []
    for job, company, owner in rows:
        score, reasons = job_signals(
            job,
            company=company,
            owner=owner,
            skill_count=int(skill_counts.get(job.id, 0)),
            application_count=int(application_counts.get(job.id, 0)),
            open_flags=int(flag_counts.get(job.id, 0)),
            native=(job.source or "").lower() == "native",
        )
        if score < min_score:
            continue
        items.append(
            {
                "id": str(job.id),
                "title": job.title,
                "status": job.status.value,
                "source": job.source,
                "location": job.location,
                "is_remote": job.is_remote,
                "salary_min": job.salary_min,
                "salary_max": job.salary_max,
                "salary_currency": job.salary_currency,
                "created_at": _iso(job.created_at),
                "applicants": int(application_counts.get(job.id, 0)),
                "skills": int(skill_counts.get(job.id, 0)),
                "open_flags": int(flag_counts.get(job.id, 0)),
                "company": {
                    "id": str(company.id),
                    "name": company.name,
                    "is_verified": company.is_verified,
                },
                "owner": {
                    "id": str(owner.id),
                    "email": owner.email,
                    "is_active": owner.is_active,
                },
                "risk_score": score,
                "risk_reasons": reasons,
            }
        )

    items.sort(key=lambda item: (-item["risk_score"], item["created_at"] or ""))
    return {
        "threshold": min_score,
        "scanned": len(rows),
        "items": items[:limit],
    }


@router.get("/moderation/suspicious-employers")
def suspicious_employers(
    _: AdminDep,
    db: DbDep,
    min_score: Annotated[int, Query(ge=1, le=20)] = SUSPICIOUS_EMPLOYER_THRESHOLD,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> dict[str, Any]:
    """Companies ranked by explainable risk signals."""
    rows = db.execute(
        select(Company, User)
        .join(User, User.id == Company.created_by_user_id)
        .order_by(Company.created_at.desc())
        .limit(500)
    ).all()

    company_ids = [company.id for company, _owner in rows]
    owner_ids = [owner.id for _company, owner in rows]
    aggregates = _company_aggregates(db, company_ids)
    owner_counts = _owner_company_counts(db, owner_ids)
    company_flags = _open_flag_counts(db, FlagTargetType.COMPANY, company_ids)

    items = []
    for company, owner in rows:
        stats = aggregates[company.id]
        score, reasons = employer_signals(
            company,
            owner=owner,
            published_jobs=stats["published_jobs"],
            application_count=stats["applications"],
            flagged_jobs=stats["flagged_jobs"],
            open_flags=int(company_flags.get(company.id, 0)),
            jobs_last_7d=stats["jobs_last_7d"],
            owner_company_count=owner_counts.get(owner.id, 1),
            native_jobs=stats["native_jobs"],
        )
        if score < min_score:
            continue
        items.append(
            {
                "id": str(company.id),
                "name": company.name,
                "industry": company.industry,
                "location": company.location,
                "website": company.website,
                "is_verified": company.is_verified,
                "created_at": _iso(company.created_at),
                "owner": {
                    "id": str(owner.id),
                    "email": owner.email,
                    "is_active": owner.is_active,
                    "is_verified": owner.is_verified,
                    "last_active_at": _iso(owner.last_active_at),
                },
                "postings": {
                    "total": stats["jobs_total"],
                    "published": stats["published_jobs"],
                    "last_7d": stats["jobs_last_7d"],
                },
                "applications": stats["applications"],
                "hires": stats["hires"],
                "open_flags": int(company_flags.get(company.id, 0)),
                "flagged_jobs": stats["flagged_jobs"],
                "risk_score": score,
                "risk_reasons": reasons,
            }
        )

    items.sort(key=lambda item: (-item["risk_score"], item["created_at"] or ""))
    return {
        "threshold": min_score,
        "scanned": len(rows),
        "items": items[:limit],
    }
