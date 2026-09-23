import logging
import os
from pathlib import Path
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_current_user
from app.core.db import SessionLocal, get_db
from app.models.enums import SkillSource
from app.models.job_family import JobFamily
from app.models.profile import Profile
from app.models.profile_entities import (
    Certification,
    Education,
    Experience,
    Project,
    Resume,
)
from app.models.skill import ProfileSkill
from app.models.user import User
from app.schemas.profile import (
    CertificationCreateRequest,
    CertificationResponse,
    CertificationUpdateRequest,
    EducationCreateRequest,
    EducationResponse,
    EducationUpdateRequest,
    ExperienceCreateRequest,
    ExperienceResponse,
    ExperienceUpdateRequest,
    ProfileDetailResponse,
    ProfileSkillItem,
    ProfileUpdateRequest,
    ProjectCreateRequest,
    ProjectResponse,
    ProjectUpdateRequest,
    ResumeResponse,
)
from app.services.skill_normalizer import resolve_skill

router = APIRouter(prefix="/profiles", tags=["profiles"])

UPLOAD_DIR = Path("/app/uploads/resumes")
if not UPLOAD_DIR.exists():
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt"}
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB


# ---------------------------------------------------------------------------
# Background task: NLP parse and profile update
# ---------------------------------------------------------------------------

def _run_resume_parse(
    profile_id: UUID,
    file_bytes: bytes,
    extension: str,
    stored_filename: str | None = None,
) -> None:
    """Called as a BackgroundTask after resume upload; never blocks the request path.

    1. Runs the configured resume parser (Gemini → regex fallback).
    2. Opens a fresh DB session.
    3. Upserts extracted skills into profile_skills.
    4. Updates years_of_experience, parsed_resume_data, education, work_experience,
       and raw_resume_text on the profile.
    """
    import logging
    from app.services.resume_parser import parse_resume

    log = logging.getLogger(__name__)
    log.info("Starting NLP parse for profile=%s ext=%s", profile_id, extension)

    try:
        result = parse_resume(file_bytes, extension)
    except Exception:
        log.exception("Resume parser raised an unhandled exception for profile=%s", profile_id)
        _set_resume_status(profile_id, stored_filename, "failed")
        return

    db: Session = SessionLocal()
    try:
        profile = db.scalar(
            select(Profile)
            .options(selectinload(Profile.skills).joinedload(ProfileSkill.skill))
            .where(Profile.id == profile_id)
        )
        if profile is None:
            log.warning("Profile %s not found during parse; aborting.", profile_id)
            return

        # --- Upsert skills via the normalizer cascade (plan §20); keep any
        # manually added skills; only add new ones, tagged with their source ---
        existing_skill_names = {ps.skill.name.lower() for ps in profile.skills}
        for parsed_skill in result.skills:
            if not parsed_skill.name:
                continue
            skill = resolve_skill(db, parsed_skill.name, category=parsed_skill.category)
            if skill.name.lower() in existing_skill_names:
                continue  # don't overwrite manually curated proficiency

            profile_skill = ProfileSkill(
                profile_id=profile.id,
                skill_id=skill.id,
                years_of_experience=parsed_skill.years,
                source=SkillSource.RESUME,
            )
            profile.skills.append(profile_skill)
            existing_skill_names.add(skill.name.lower())

        # --- Update profile structured fields ---
        profile.raw_resume_text = result.raw_text or profile.raw_resume_text

        # Only overwrite years_of_experience if not already set by the user
        if profile.years_of_experience is None and result.years_of_experience is not None:
            profile.years_of_experience = result.years_of_experience

        if result.education:
            profile.education = [e.model_dump(exclude_none=True) for e in result.education]

        if result.work_experience:
            profile.work_experience = [w.model_dump(exclude_none=True) for w in result.work_experience]

        profile.parsed_resume_data = {
            "parser_used": result.parser_used,
            "skills_extracted": len(result.skills),
            "years_of_experience": result.years_of_experience,
            "seniority": getattr(result, "seniority", None),
        }

        # --- Close out the versioned resume row with evidence (plan §3) ---
        resume = _find_resume(db, profile_id, stored_filename)
        if resume is not None:
            resume.parse_status = "parsed"
            resume.parser_used = result.parser_used
            resume.extracted = {
                "skills": [s.name for s in result.skills if s.name],
                "years_of_experience": result.years_of_experience,
                "seniority": getattr(result, "seniority", None),
            }
            resume.evidence = getattr(result, "evidence", None)

        db.commit()
        log.info(
            "NLP parse complete for profile=%s: parser=%s skills=%d yoe=%s",
            profile_id, result.parser_used, len(result.skills), result.years_of_experience,
        )

    except Exception:
        db.rollback()
        log.exception("Failed to persist parsed resume data for profile=%s", profile_id)
    finally:
        db.close()


def _find_resume(db: Session, profile_id: UUID, stored_filename: str | None) -> Resume | None:
    if stored_filename:
        row = db.scalar(
            select(Resume).where(
                Resume.profile_id == profile_id,
                Resume.file_path == stored_filename,
            )
        )
        if row is not None:
            return row
    return db.scalar(
        select(Resume)
        .where(Resume.profile_id == profile_id, Resume.parse_status == "parsing")
        .order_by(Resume.created_at.desc())
    )


def _set_resume_status(
    profile_id: UUID,
    stored_filename: str | None,
    status_value: str,
) -> None:
    """Best-effort resume row status update in its own session."""
    db = SessionLocal()
    try:
        resume = _find_resume(db, profile_id, stored_filename)
        if resume is not None:
            resume.parse_status = status_value
            db.commit()
    except Exception:
        db.rollback()
        logging.getLogger(__name__).exception(
            "Failed to update resume status for profile=%s", profile_id
        )
    finally:
        db.close()


def _format_profile_response(profile: Profile) -> ProfileDetailResponse:
    skills_list: list[ProfileSkillItem] = []
    if profile.skills:
        for ps in profile.skills:
            skills_list.append(
                ProfileSkillItem(
                    skill_name=ps.skill.name,
                    category=ps.skill.category,
                    proficiency_level=ps.proficiency_level,
                    years_of_experience=ps.years_of_experience,
                )
            )

    return ProfileDetailResponse(
        id=profile.id,
        user_id=profile.user_id,
        first_name=profile.first_name,
        last_name=profile.last_name,
        headline=profile.headline,
        bio=profile.bio,
        location=profile.location,
        phone=profile.phone,
        resume_url=profile.resume_url,
        raw_resume_text=profile.raw_resume_text,
        parsed_resume_data=profile.parsed_resume_data,
        years_of_experience=profile.years_of_experience,
        education=profile.education,
        work_experience=profile.work_experience,
        skills=skills_list,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
        # ---- additive Phase 1 (plan §2/§3) ----
        expected_salary_min=profile.expected_salary_min,
        expected_salary_max=profile.expected_salary_max,
        expected_salary_currency=profile.expected_salary_currency,
        preferred_work_mode=profile.preferred_work_mode,
        career_interests=profile.career_interests,
        preferred_locations=profile.preferred_locations,
        target_family=(
            profile.target_family.name if profile.target_family is not None else None
        ),
        education_rows=profile.education_rows or [],
        experience_rows=profile.experience_rows or [],
        project_rows=profile.project_rows or [],
        certification_rows=profile.certification_rows or [],
        resumes=sorted(
            profile.resumes or [], key=lambda r: r.created_at, reverse=True
        ),
    )


@router.get("/me", response_model=ProfileDetailResponse)
def get_my_profile(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ProfileDetailResponse:
    """Retrieve the current user's profile with structured skills and resume details."""
    profile = db.scalar(
        select(Profile)
        .options(selectinload(Profile.skills).joinedload(ProfileSkill.skill))
        .where(Profile.user_id == current_user.id)
    )

    if profile is None:
        # Automatically initialize profile if missing
        profile = Profile(
            user_id=current_user.id,
            first_name="",
            last_name="",
        )
        db.add(profile)
        db.commit()
        db.refresh(profile)

    return _format_profile_response(profile)


@router.put("/me", response_model=ProfileDetailResponse)
def update_my_profile(
    payload: ProfileUpdateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ProfileDetailResponse:
    """Update profile structured fields, experience, education, and associated skills."""
    profile = db.scalar(
        select(Profile)
        .options(selectinload(Profile.skills).joinedload(ProfileSkill.skill))
        .where(Profile.user_id == current_user.id)
    )

    if profile is None:
        profile = Profile(user_id=current_user.id)
        db.add(profile)
        db.flush()

    if payload.first_name is not None:
        profile.first_name = payload.first_name.strip()
    if payload.last_name is not None:
        profile.last_name = payload.last_name.strip()
    if payload.headline is not None:
        profile.headline = payload.headline.strip() or None
    if payload.bio is not None:
        profile.bio = payload.bio.strip() or None
    if payload.location is not None:
        profile.location = payload.location.strip() or None
    if payload.phone is not None:
        profile.phone = payload.phone.strip() or None
    if payload.years_of_experience is not None:
        profile.years_of_experience = payload.years_of_experience
    if payload.education is not None:
        profile.education = [e.model_dump() for e in payload.education]
    if payload.work_experience is not None:
        profile.work_experience = [w.model_dump() for w in payload.work_experience]

    # ---- additive Phase 1: preferences (None = leave unchanged; "" clears) ----
    if payload.expected_salary_min is not None:
        profile.expected_salary_min = payload.expected_salary_min
    if payload.expected_salary_max is not None:
        profile.expected_salary_max = payload.expected_salary_max
    if payload.expected_salary_currency is not None:
        profile.expected_salary_currency = (
            payload.expected_salary_currency.strip().upper()[:10] or "USD"
        )
    if payload.preferred_work_mode is not None:
        profile.preferred_work_mode = payload.preferred_work_mode
    if payload.career_interests is not None:
        profile.career_interests = [
            i.strip() for i in payload.career_interests if i and i.strip()
        ]
    if payload.preferred_locations is not None:
        profile.preferred_locations = [
            l.strip() for l in payload.preferred_locations if l and l.strip()
        ]
    if payload.target_family is not None:
        raw_family = payload.target_family.strip()
        if not raw_family:
            profile.target_job_family_id = None  # explicit clear
        else:
            family = db.scalar(
                select(JobFamily).where(func.lower(JobFamily.name) == raw_family.lower())
            )
            if family is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Unknown job family '{raw_family}'.",
                )
            profile.target_job_family_id = family.id

    if payload.skills is not None:
        # Clear existing associations
        profile.skills.clear()
        db.flush()

        for skill_item in payload.skills:
            if not skill_item.skill_name.strip():
                continue
            # Normalizer cascade: exact → alias → fuzzy → new (plan §20)
            skill = resolve_skill(db, skill_item.skill_name, category=skill_item.category)
            profile_skill = ProfileSkill(
                profile_id=profile.id,
                skill_id=skill.id,
                proficiency_level=skill_item.proficiency_level,
                years_of_experience=skill_item.years_of_experience,
                source=SkillSource.MANUAL,
            )
            profile.skills.append(profile_skill)

    db.commit()

    # Re-query fresh with relations
    updated_profile = db.scalar(
        select(Profile)
        .options(selectinload(Profile.skills).joinedload(ProfileSkill.skill))
        .where(Profile.id == profile.id)
    )
    return _format_profile_response(updated_profile)


@router.post("/me/resume")
def upload_resume(
    file: Annotated[UploadFile, File(...)],
    background_tasks: BackgroundTasks,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """Securely upload a resume (PDF, DOCX, TXT ≤ 10 MB) and trigger async NLP parsing.

    The endpoint returns immediately after storing the file.  NLP extraction
    (skills, years of experience, education, work history) runs in the background
    and populates the profile within a few seconds.
    """
    profile = db.scalar(select(Profile).where(Profile.user_id == current_user.id))
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Profile not found for this user account.",
        )

    file_ext = Path(file.filename or "").suffix.lower()
    if file_ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file format '{file_ext}'. Allowed formats: {list(ALLOWED_EXTENSIONS)}",
        )

    # Read and check size
    content = file.file.read()
    if len(content) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds maximum allowed limit of {MAX_FILE_SIZE_BYTES // (1024 * 1024)}MB.",
        )

    if len(content) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file cannot be empty.",
        )

    safe_filename = f"{profile.id}_{uuid4().hex[:8]}{file_ext}"
    target_path = UPLOAD_DIR / safe_filename

    with open(target_path, "wb") as f:
        f.write(content)

    resume_url = f"/api/v1/profiles/me/resume?file={safe_filename}"
    profile.resume_url = resume_url
    profile.parsed_resume_data = {"status": "parsing", "parser_used": None}  # optimistic UI hint
    # Versioned resume row (plan §3) — extraction + evidence land here after parse
    db.add(
        Resume(
            profile_id=profile.id,
            file_path=safe_filename,
            original_filename=file.filename,
            parse_status="parsing",
        )
    )
    db.commit()

    # Enqueue NLP parse — runs after response is sent
    background_tasks.add_task(
        _run_resume_parse,
        profile_id=profile.id,
        file_bytes=content,
        extension=file_ext,
        stored_filename=safe_filename,
    )

    return {
        "status": "uploaded",
        "message": "Resume uploaded. NLP parsing started in background — check profile in a few seconds.",
        "filename": file.filename,
        "stored_filename": safe_filename,
        "resume_url": resume_url,
        "size_bytes": len(content),
        "parsing": "started",
    }


@router.get("/me/resume")
def download_resume(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    file: str | None = None,
):
    """Stream and download the current user's uploaded resume."""
    profile = db.scalar(select(Profile).where(Profile.user_id == current_user.id))
    if profile is None or not profile.resume_url:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No resume has been uploaded for this profile.",
        )

    # Extract stored filename from query or resume_url
    stored_name = file
    if not stored_name:
        if "file=" in profile.resume_url:
            stored_name = profile.resume_url.split("file=")[-1]
        else:
            stored_name = Path(profile.resume_url).name

    target_path = UPLOAD_DIR / stored_name
    # Ownership check (plan §21): stored files are "{profile_id}_{hex}{ext}" —
    # reject cross-profile reads and path traversal outright.
    if not stored_name.startswith(f"{profile.id}_") or ".." in stored_name:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The resume file was not found on the server.",
        )
    if not target_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The resume file was not found on the server.",
        )

    media_type = "application/pdf"
    if target_path.suffix == ".docx":
        media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    elif target_path.suffix == ".txt":
        media_type = "text/plain"

    return FileResponse(
        path=target_path,
        media_type=media_type,
        filename=f"Resume_{profile.first_name}_{profile.last_name}{target_path.suffix}",
    )


# ---------------------------------------------------------------------------
# Structured sub-resources (plan §3): education / experience / projects /
# certifications / resumes — every row strictly scoped to the caller's profile
# ---------------------------------------------------------------------------


def _my_profile_or_404(db: Session, current_user: User) -> Profile:
    profile = db.scalar(select(Profile).where(Profile.user_id == current_user.id))
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Profile not found for this user account.",
        )
    return profile


def _owned_row_or_404(db: Session, profile: Profile, model_cls, row_id: UUID):
    row = db.scalar(
        select(model_cls).where(
            model_cls.id == row_id,
            model_cls.profile_id == profile.id,
        )
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{model_cls.__name__} entry not found.",
        )
    return row


# ---- education ----


@router.get("/me/education", response_model=list[EducationResponse])
def list_education(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[EducationResponse]:
    profile = _my_profile_or_404(db, current_user)
    return db.scalars(
        select(Education)
        .where(Education.profile_id == profile.id)
        .order_by(Education.is_primary.desc(), Education.created_at.desc())
    ).all()


@router.post(
    "/me/education",
    response_model=EducationResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_education(
    payload: EducationCreateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> EducationResponse:
    profile = _my_profile_or_404(db, current_user)
    data = payload.model_dump()
    if data.get("is_primary"):
        _clear_primary_educations(db, profile.id)
    row = Education(profile_id=profile.id, **data)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _clear_primary_educations(
    db: Session, profile_id: UUID, exclude_id: UUID | None = None
) -> None:
    query = select(Education).where(
        Education.profile_id == profile_id,
        Education.is_primary.is_(True),
    )
    if exclude_id is not None:
        query = query.where(Education.id != exclude_id)
    for row in db.scalars(query):
        row.is_primary = False


@router.patch("/me/education/{row_id}", response_model=EducationResponse)
def update_education(
    row_id: UUID,
    payload: EducationUpdateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> EducationResponse:
    profile = _my_profile_or_404(db, current_user)
    row = _owned_row_or_404(db, profile, Education, row_id)
    data = payload.model_dump(exclude_unset=True)
    if data.get("is_primary"):
        _clear_primary_educations(db, profile.id, exclude_id=row_id)
    for field, value in data.items():
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/me/education/{row_id}")
def delete_education(
    row_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    profile = _my_profile_or_404(db, current_user)
    row = _owned_row_or_404(db, profile, Education, row_id)
    db.delete(row)
    db.commit()
    return {"status": "deleted", "id": str(row_id)}


# ---- experience ----


@router.get("/me/experience", response_model=list[ExperienceResponse])
def list_experience(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[ExperienceResponse]:
    profile = _my_profile_or_404(db, current_user)
    return db.scalars(
        select(Experience)
        .where(Experience.profile_id == profile.id)
        .order_by(Experience.created_at.desc())
    ).all()


@router.post(
    "/me/experience",
    response_model=ExperienceResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_experience(
    payload: ExperienceCreateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ExperienceResponse:
    profile = _my_profile_or_404(db, current_user)
    row = Experience(profile_id=profile.id, **payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.patch("/me/experience/{row_id}", response_model=ExperienceResponse)
def update_experience(
    row_id: UUID,
    payload: ExperienceUpdateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ExperienceResponse:
    profile = _my_profile_or_404(db, current_user)
    row = _owned_row_or_404(db, profile, Experience, row_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/me/experience/{row_id}")
def delete_experience(
    row_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    profile = _my_profile_or_404(db, current_user)
    row = _owned_row_or_404(db, profile, Experience, row_id)
    db.delete(row)
    db.commit()
    return {"status": "deleted", "id": str(row_id)}


# ---- projects ----


@router.get("/me/projects", response_model=list[ProjectResponse])
def list_projects(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[ProjectResponse]:
    profile = _my_profile_or_404(db, current_user)
    return db.scalars(
        select(Project)
        .where(Project.profile_id == profile.id)
        .order_by(Project.created_at.desc())
    ).all()


@router.post(
    "/me/projects",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_project(
    payload: ProjectCreateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ProjectResponse:
    profile = _my_profile_or_404(db, current_user)
    row = Project(profile_id=profile.id, **payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.patch("/me/projects/{row_id}", response_model=ProjectResponse)
def update_project(
    row_id: UUID,
    payload: ProjectUpdateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ProjectResponse:
    profile = _my_profile_or_404(db, current_user)
    row = _owned_row_or_404(db, profile, Project, row_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/me/projects/{row_id}")
def delete_project(
    row_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    profile = _my_profile_or_404(db, current_user)
    row = _owned_row_or_404(db, profile, Project, row_id)
    db.delete(row)
    db.commit()
    return {"status": "deleted", "id": str(row_id)}


# ---- certifications ----


@router.get("/me/certifications", response_model=list[CertificationResponse])
def list_certifications(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[CertificationResponse]:
    profile = _my_profile_or_404(db, current_user)
    return db.scalars(
        select(Certification)
        .where(Certification.profile_id == profile.id)
        .order_by(Certification.created_at.desc())
    ).all()


@router.post(
    "/me/certifications",
    response_model=CertificationResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_certification(
    payload: CertificationCreateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> CertificationResponse:
    profile = _my_profile_or_404(db, current_user)
    row = Certification(profile_id=profile.id, **payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.patch("/me/certifications/{row_id}", response_model=CertificationResponse)
def update_certification(
    row_id: UUID,
    payload: CertificationUpdateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> CertificationResponse:
    profile = _my_profile_or_404(db, current_user)
    row = _owned_row_or_404(db, profile, Certification, row_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/me/certifications/{row_id}")
def delete_certification(
    row_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    profile = _my_profile_or_404(db, current_user)
    row = _owned_row_or_404(db, profile, Certification, row_id)
    db.delete(row)
    db.commit()
    return {"status": "deleted", "id": str(row_id)}


# ---- resume upload history ----


@router.get("/me/resumes", response_model=list[ResumeResponse])
def list_resumes(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[ResumeResponse]:
    profile = _my_profile_or_404(db, current_user)
    return db.scalars(
        select(Resume)
        .where(Resume.profile_id == profile.id)
        .order_by(Resume.created_at.desc())
    ).all()
