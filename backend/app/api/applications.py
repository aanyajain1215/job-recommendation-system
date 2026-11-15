"""Applications API.

Handles:
- POST  /jobs/{job_id}/apply                 — Apply to a job (atomic application + interaction log + status history)
- GET   /applications/me                     — List candidate's applications (paginated)
- GET   /applications/me/stats               — Lightweight aggregate stats for dashboard tiles
- GET   /applications/{id}/history           — Audit trail of application status changes
- GET   /employer/jobs/{job_id}/applications — Employer view of applicants (with strict ownership check)
- PATCH /employer/applications/{id}/status   — Employer update applicant review status (with atomic history)
"""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_current_user, require_roles
from app.core.db import get_db
from app.models.application import Application, ApplicationStatusHistory
from app.models.enums import ApplicationStatus, InteractionType, JobStatus, UserRole
from app.models.interaction import Interaction
from app.models.job import Job
from app.models.profile import Profile
from app.models.skill import JobSkill, Skill
from app.models.user import User
from app.schemas.applications import (
    ApplicantProfileSummary,
    ApplicationCreate,
    ApplicationOut,
    ApplicationStatsOut,
    ApplicationStatusHistoryOut,
    ApplicationStatusUpdate,
    EmployerApplicationOut,
    JobSummaryOut,
)
from app.schemas.user import CompanySummary

router = APIRouter(tags=["applications"])


def _format_job_summary(job: Job) -> JobSummaryOut:
    return JobSummaryOut(
        id=job.id,
        title=job.title,
        location=job.location,
        is_remote=job.is_remote,
        employment_type=job.employment_type,
        experience_level=job.experience_level,
        salary_min=job.salary_min,
        salary_max=job.salary_max,
        salary_currency=job.salary_currency,
        external_url=job.external_url,
        company=CompanySummary.model_validate(job.company) if job.company else None,
    )


def _format_application_out(app_rec: Application, job: Job | None = None) -> ApplicationOut:
    target_job = job or app_rec.job
    return ApplicationOut(
        id=app_rec.id,
        job_id=app_rec.job_id,
        user_id=app_rec.user_id,
        status=app_rec.status,
        cover_note=app_rec.cover_note,
        resume_url_snapshot=app_rec.resume_url_snapshot,
        applied_at=app_rec.applied_at,
        created_at=app_rec.applied_at,
        updated_at=app_rec.updated_at,
        job=_format_job_summary(target_job) if target_job else None,
    )


def _format_employer_application_out(app_rec: Application) -> EmployerApplicationOut:
    profile = app_rec.profile
    user = app_rec.user
    applicant_summary = None
    if profile:
        applicant_summary = ApplicantProfileSummary(
            id=profile.id,
            user_id=profile.user_id,
            first_name=profile.first_name,
            last_name=profile.last_name,
            headline=profile.headline,
            location=profile.location,
            phone=profile.phone,
            resume_url=profile.resume_url,
            years_of_experience=profile.years_of_experience,
        )

    return EmployerApplicationOut(
        id=app_rec.id,
        job_id=app_rec.job_id,
        user_id=app_rec.user_id,
        status=app_rec.status,
        cover_note=app_rec.cover_note,
        resume_url_snapshot=app_rec.resume_url_snapshot,
        applied_at=app_rec.applied_at,
        created_at=app_rec.applied_at,
        updated_at=app_rec.updated_at,
        applicant=applicant_summary,
        user_email=user.email if user else None,
    )


def _record_status_transition(
    db: Session,
    application: Application,
    new_status: ApplicationStatus,
    changed_by_user_id: UUID | None,
    reason: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> ApplicationStatusHistory | None:
    """Atomically updates application status and records an auditable history transition.

    No-op update check: if new_status equals the current status, no duplicate history is written.
    """
    if application.status == new_status:
        return None

    prev_status = application.status
    application.status = new_status
    history = ApplicationStatusHistory(
        application_id=application.id,
        previous_status=prev_status,
        new_status=new_status,
        changed_by_user_id=changed_by_user_id,
        reason=reason,
        metadata_=metadata,
    )
    db.add(history)
    return history


# ---------------------------------------------------------------------------
# Seeker Endpoints
# ---------------------------------------------------------------------------

@router.post(
    "/jobs/{job_id}/apply",
    response_model=ApplicationOut,
    status_code=status.HTTP_201_CREATED,
    summary="Apply for an active job posting",
)
def apply_to_job(
    job_id: UUID,
    payload: ApplicationCreate,
    current_user: Annotated[User, Depends(require_roles(UserRole.JOB_SEEKER))],
    db: Annotated[Session, Depends(get_db)],
) -> ApplicationOut:
    """Submit an application for a published job."""
    # 1. Verify Job exists and is published
    job = db.scalar(
        select(Job)
        .options(selectinload(Job.company))
        .where(Job.id == job_id, Job.status == JobStatus.PUBLISHED)
    )
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job posting not found or not currently accepting applications.",
        )

    # 2. Check for duplicate application
    existing = db.scalar(
        select(Application).where(
            Application.job_id == job_id,
            Application.user_id == current_user.id,
        )
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Already applied to this job.",
        )

    # 3. Retrieve or ensure candidate Profile exists
    profile = db.scalar(select(Profile).where(Profile.user_id == current_user.id))
    if not profile:
        profile = Profile(
            user_id=current_user.id,
            first_name=current_user.email.split("@")[0].capitalize(),
            last_name="",
        )
        db.add(profile)
        db.flush()

    # Verify profile ownership (Phase 1.1)
    if profile.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Profile does not belong to the current user.",
        )

    # 4. Atomic application + initial status history + interaction creation
    app_record = Application(
        job_id=job.id,
        user_id=current_user.id,
        profile_id=profile.id,
        status=ApplicationStatus.APPLIED,
        cover_note=payload.cover_note.strip() if payload.cover_note else None,
        resume_url_snapshot=profile.resume_url,
    )
    db.add(app_record)
    db.flush()

    # Initial status history entry (Phase 2.3)
    init_history = ApplicationStatusHistory(
        application_id=app_record.id,
        previous_status=None,
        new_status=ApplicationStatus.APPLIED,
        changed_by_user_id=current_user.id,
        reason=payload.cover_note.strip() if payload.cover_note else "Initial application submission",
    )
    db.add(init_history)

    apply_interaction = Interaction(
        user_id=current_user.id,
        job_id=job.id,
        event_type=InteractionType.APPLY,
        metadata_={
            "source": "apply_api",
            "has_cover_note": bool(payload.cover_note),
            "resume_url_snapshot": profile.resume_url,
        },
    )
    db.add(apply_interaction)

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Already applied to this job.",
        ) from exc

    db.refresh(app_record)
    return _format_application_out(app_record, job=job)


@router.get(
    "/applications",
    response_model=list[ApplicationOut],
    summary="List current candidate's applications (incl. saved)",
)
@router.get(
    "/applications/me",
    response_model=list[ApplicationOut],
    summary="List current candidate's applications",
)
def get_my_applications(
    current_user: Annotated[User, Depends(require_roles(UserRole.JOB_SEEKER))],
    db: Annotated[Session, Depends(get_db)],
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    status_filter: Annotated[ApplicationStatus | None, Query(alias="status")] = None,
) -> list[ApplicationOut]:
    """Return paginated list of applications submitted by the calling job seeker."""
    stmt = (
        select(Application)
        .options(selectinload(Application.job).selectinload(Job.company))
        .where(Application.user_id == current_user.id)
    )

    if status_filter is not None:
        stmt = stmt.where(Application.status == status_filter)

    offset = (page - 1) * limit
    stmt = stmt.order_by(Application.applied_at.desc()).offset(offset).limit(limit)
    rows = db.scalars(stmt).all()

    return [_format_application_out(r) for r in rows]


def _successful_skill_observation(db: Session, user_id) -> tuple[list[str], str]:
    """§18: 'skills in your successful applications …' — observation only."""
    success = (
        ApplicationStatus.SHORTLISTED,
        ApplicationStatus.INTERVIEW,
        ApplicationStatus.OFFER,
        ApplicationStatus.HIRED,
    )
    rows = db.execute(
        select(Skill.name, func.count(Skill.id))
        .join(JobSkill, JobSkill.skill_id == Skill.id)
        .join(Job, Job.id == JobSkill.job_id)
        .join(Application, Application.job_id == Job.id)
        .where(
            Application.user_id == user_id,
            Application.status.in_(success),
            JobSkill.is_required.is_(True),
        )
        .group_by(Skill.name)
        .order_by(func.count(Skill.id).desc(), Skill.name.asc())
        .limit(8)
    ).all()
    names = [r[0] for r in rows]
    note = (
        "Common skills across your shortlisted and interview-stage applications: "
        + (", ".join(names) if names else "apply to a few roles to see patterns here.")
    )
    return names, note


@router.get(
    "/applications/stats",
    response_model=ApplicationStatsOut,
    summary="Application pipeline analytics incl. skill observation (§18)",
)
@router.get(
    "/applications/me/stats",
    response_model=ApplicationStatsOut,
    summary="Get candidate application pipeline aggregate stats",
)
def get_my_application_stats(
    current_user: Annotated[User, Depends(require_roles(UserRole.JOB_SEEKER))],
    db: Annotated[Session, Depends(get_db)],
) -> ApplicationStatsOut:
    """Lightweight aggregate endpoint powering candidate dashboard pipeline tiles."""
    rows = db.execute(
        select(Application.status, func.count(Application.id))
        .where(Application.user_id == current_user.id)
        .group_by(Application.status)
    ).all()

    counts = {r[0]: r[1] for r in rows}
    total = sum(counts.values())
    successful, note = _successful_skill_observation(db, current_user.id)

    return ApplicationStatsOut(
        total_applied=total,
        applied=counts.get(ApplicationStatus.APPLIED, 0),
        viewed=counts.get(ApplicationStatus.VIEWED, 0),
        shortlisted=counts.get(ApplicationStatus.SHORTLISTED, 0),
        interview=counts.get(ApplicationStatus.INTERVIEW, 0),
        rejected=counts.get(ApplicationStatus.REJECTED, 0),
        offer=counts.get(ApplicationStatus.OFFER, 0),
        hired=counts.get(ApplicationStatus.HIRED, 0),
        saved=counts.get(ApplicationStatus.SAVED, 0),
        successful_skills=successful,
        observation_note=note,
    )


@router.post(
    "/jobs/{job_id}/save",
    response_model=ApplicationOut,
    status_code=status.HTTP_201_CREATED,
    summary="Save a job for later (status=saved)",
)
def save_job_for_later(
    job_id: UUID,
    current_user: Annotated[User, Depends(require_roles(UserRole.JOB_SEEKER))],
    db: Annotated[Session, Depends(get_db)],
) -> ApplicationOut:
    """Idempotent save → Application(status=SAVED) + a 'save' interaction + status history."""
    job = db.scalar(
        select(Job).options(selectinload(Job.company)).where(Job.id == job_id)
    )
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Job posting not found."
        )

    existing = db.scalar(
        select(Application).where(
            Application.job_id == job_id,
            Application.user_id == current_user.id,
        )
    )
    if existing is not None:
        if existing.status != ApplicationStatus.SAVED:
            _record_status_transition(
                db,
                existing,
                ApplicationStatus.SAVED,
                current_user.id,
                reason="Saved job for later",
            )
            db.commit()
            db.refresh(existing)
        return _format_application_out(existing, job=job)

    profile = db.scalar(select(Profile).where(Profile.user_id == current_user.id))
    if not profile:
        profile = Profile(
            user_id=current_user.id,
            first_name=current_user.email.split("@")[0].capitalize(),
            last_name="",
        )
        db.add(profile)
        db.flush()

    record = Application(
        job_id=job.id,
        user_id=current_user.id,
        profile_id=profile.id,
        status=ApplicationStatus.SAVED,
        resume_url_snapshot=profile.resume_url,
    )
    db.add(record)
    db.flush()

    init_history = ApplicationStatusHistory(
        application_id=record.id,
        previous_status=None,
        new_status=ApplicationStatus.SAVED,
        changed_by_user_id=current_user.id,
        reason="Saved job for later",
    )
    db.add(init_history)

    db.add(
        Interaction(
            user_id=current_user.id,
            job_id=job.id,
            event_type=InteractionType.SAVE,
            metadata_={"source": "save_api"},
        )
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        again = db.scalar(
            select(Application).where(
                Application.job_id == job_id,
                Application.user_id == current_user.id,
            )
        )
        if again is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Could not save this job.",
            ) from None
        return _format_application_out(again, job=job)

    db.refresh(record)
    return _format_application_out(record, job=job)


@router.patch(
    "/applications/{application_id}",
    response_model=ApplicationOut,
    summary="Update your own application pipeline status (tracker, §19)",
)
def update_my_application(
    application_id: UUID,
    payload: ApplicationStatusUpdate,
    current_user: Annotated[User, Depends(require_roles(UserRole.JOB_SEEKER))],
    db: Annotated[Session, Depends(get_db)],
) -> ApplicationOut:
    """Seeker-side status move (applied → viewed → shortlisted → …) with atomic history."""
    record = db.scalar(
        select(Application)
        .options(selectinload(Application.job).selectinload(Job.company))
        .where(Application.id == application_id)
    )
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Application record not found.",
        )
    if record.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not own this application.",
        )

    _record_status_transition(
        db,
        record,
        payload.status,
        current_user.id,
        reason=payload.reason or "Candidate updated application status",
    )
    db.commit()
    db.refresh(record)
    return _format_application_out(record)


@router.get(
    "/applications/{application_id}/history",
    response_model=list[ApplicationStatusHistoryOut],
    summary="Retrieve audit status history for an application",
)
def get_application_status_history(
    application_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[ApplicationStatusHistoryOut]:
    """Retrieve audit trail of status transitions for an application.

    Strict authorization:
    - Seeker who submitted the application
    - Employer who posted the corresponding job
    - Admin
    """
    app_rec = db.scalar(
        select(Application)
        .options(selectinload(Application.job))
        .where(Application.id == application_id)
    )
    if not app_rec:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Application record not found.",
        )

    is_seeker = app_rec.user_id == current_user.id
    is_employer = (
        app_rec.job.posted_by_user_id == current_user.id
        if app_rec.job
        else False
    )
    is_admin = current_user.role == UserRole.ADMIN

    if not (is_seeker or is_employer or is_admin):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to view status history for this application.",
        )

    stmt = (
        select(ApplicationStatusHistory)
        .where(ApplicationStatusHistory.application_id == application_id)
        .order_by(ApplicationStatusHistory.changed_at.asc())
    )
    rows = db.scalars(stmt).all()

    return [
        ApplicationStatusHistoryOut(
            id=r.id,
            application_id=r.application_id,
            previous_status=r.previous_status,
            new_status=r.new_status,
            changed_at=r.changed_at,
            changed_by_user_id=r.changed_by_user_id,
            reason=r.reason,
            metadata=r.metadata_,
        )
        for r in rows
    ]


@router.delete(
    "/applications/{application_id}",
    status_code=status.HTTP_200_OK,
    summary="Remove a saved job (unsave)",
)
def unsave_job(
    application_id: UUID,
    current_user: Annotated[User, Depends(require_roles(UserRole.JOB_SEEKER))],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """Only saved rows are removable; pipeline moves go through PATCH."""
    record = db.get(Application, application_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Application record not found.",
        )
    if record.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not own this application.",
        )
    if record.status != ApplicationStatus.SAVED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only saved jobs can be removed; use PATCH for pipeline statuses.",
        )
    db.delete(record)
    db.commit()
    return {"status": "removed", "id": str(application_id)}


# ---------------------------------------------------------------------------
# Employer Endpoints
# ---------------------------------------------------------------------------

@router.get(
    "/employer/jobs/{job_id}/applications",
    response_model=list[EmployerApplicationOut],
    summary="List applicants for a specific employer job posting",
)
def get_job_applicants(
    job_id: UUID,
    current_user: Annotated[User, Depends(require_roles(UserRole.EMPLOYER, UserRole.ADMIN))],
    db: Annotated[Session, Depends(get_db)],
) -> list[EmployerApplicationOut]:
    """Retrieve all candidate applications for an employer's job posting."""
    job = db.scalar(select(Job).where(Job.id == job_id))
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job posting not found.",
        )

    # Ownership check
    if job.posted_by_user_id != current_user.id and current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to view applicants for this job posting.",
        )

    stmt = (
        select(Application)
        .options(
            selectinload(Application.profile),
            selectinload(Application.user),
        )
        .where(Application.job_id == job_id)
        .order_by(Application.applied_at.desc())
    )
    rows = db.scalars(stmt).all()

    return [_format_employer_application_out(r) for r in rows]


@router.patch(
    "/employer/applications/{application_id}/status",
    response_model=EmployerApplicationOut,
    summary="Update candidate application pipeline status",
)
def update_application_status(
    application_id: UUID,
    payload: ApplicationStatusUpdate,
    current_user: Annotated[User, Depends(require_roles(UserRole.EMPLOYER, UserRole.ADMIN))],
    db: Annotated[Session, Depends(get_db)],
) -> EmployerApplicationOut:
    """Employer updates candidate status in the hiring pipeline (with atomic audit history)."""
    app_record = db.scalar(
        select(Application)
        .options(
            selectinload(Application.job),
            selectinload(Application.profile),
            selectinload(Application.user),
        )
        .where(Application.id == application_id)
    )
    if not app_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Application record not found.",
        )

    # Verify caller owns the job associated with this application
    if app_record.job.posted_by_user_id != current_user.id and current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to modify this application.",
        )

    _record_status_transition(
        db,
        app_record,
        payload.status,
        current_user.id,
        reason=payload.reason or "Employer moved candidate pipeline status",
    )
    db.commit()
    db.refresh(app_record)

    return _format_employer_application_out(app_record)
