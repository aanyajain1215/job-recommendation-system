import math
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_current_user, require_roles
from app.core.db import get_db
from app.models.application import Application
from app.models.company import Company
from app.models.enums import EmploymentType, ExperienceLevel, JobStatus, UserRole, WorkMode
from app.models.job import Job
from app.models.job_family import JobFamily
from app.models.skill import JobSkill, Skill
from app.models.user import User
from app.schemas.job import (
    JobCreateRequest,
    JobDetailResponse,
    JobListResponse,
    JobNlResponse,
    JobSkillRequirement,
    JobUpdateRequest,
)
from app.schemas.user import CompanySummary
from app.services import live_jobs, nl_search
from app.services.skill_normalizer import build_db_normalizer, resolve_skill

router = APIRouter(tags=["jobs"])

# Platform matches considered for a merged (platform + live) search page —
# enough for any realistic on-platform corpus, bounded so one request can't
# drag thousands of rows into memory.
_MERGE_PLATFORM_CAP = 500

# Unfiltered browse fills from this live query so the catalog page shows
# real-time openings instead of (an empty or fixed) pre-loaded corpus.
_DEFAULT_BROWSE_QUERY = "software engineer"


def _format_job_response(
    job: Job,
    applicant_count: int = 0,
    relevance_score: float | None = None,
    snippet: str | None = None,
) -> JobDetailResponse:
    skills_list: list[JobSkillRequirement] = []
    if job.skills:
        for js in job.skills:
            skills_list.append(
                JobSkillRequirement(
                    skill_name=js.skill.name,
                    category=js.skill.category,
                    is_required=js.is_required,
                    importance_weight=js.importance_weight,
                )
            )

    return JobDetailResponse(
        id=str(job.id),
        company_id=job.company_id,
        posted_by_user_id=job.posted_by_user_id,
        title=job.title,
        description=job.description,
        requirements=job.requirements,
        employment_type=job.employment_type,
        experience_level=job.experience_level,
        location=job.location,
        is_remote=job.is_remote,
        salary_min=job.salary_min,
        salary_max=job.salary_max,
        salary_currency=job.salary_currency,
        status=job.status,
        created_at=job.created_at,
        updated_at=job.updated_at,
        company=CompanySummary.model_validate(job.company),
        skills=skills_list,
        applicant_count=applicant_count,
        relevance_score=relevance_score,
        snippet=snippet,
        family=job.family.name if job.family is not None else None,
        external_url=job.external_url,
        source=getattr(job, "source", None) or "native",
    )


def _paginate_merged(
    platform_items: list[JobDetailResponse],
    *,
    live_query: str,
    live_location: str | None,
    sort_by: str,
    offset: int,
    page_size: int,
) -> tuple[list[JobDetailResponse], int]:
    """One offset-paginated window over platform matches + live Adzuna results.

    Platform postings come first (they are applyable/tracked on this site),
    live results fill the rest — fetched page-by-page from Adzuna at request
    time.  Provider failures degrade to platform-only (search_postings
    returns ([], 0)).  Dedupe is title+company against the platform window
    and within the live slice; `total` keeps Adzuna's own count, so it can
    run slightly high when dedupe drops a duplicate.
    """
    p_count = len(platform_items)
    live_total = 0
    live_slice: list[JobDetailResponse] = []

    start = max(0, offset - p_count)
    end = offset + page_size - p_count
    if end > 0:
        first_page = start // page_size + 1
        last_page = (end - 1) // page_size + 1
        pages: dict[int, list[dict]] = {}
        for page_no in range(first_page, last_page + 1):
            rows, total = live_jobs.search_postings(
                live_query,
                location=live_location,
                page=page_no,
                page_size=page_size,
                sort_by=sort_by,
            )
            if page_no == first_page:
                live_total = total
            pages[page_no] = rows

        platform_keys = {
            f"{(p.title or '').strip().lower()}|{(p.company.name or '').strip().lower()}"
            for p in platform_items
        }
        seen: set[str] = set()
        for index in range(start, end):
            rows = pages.get(index // page_size + 1) or []
            within = index % page_size
            if within >= len(rows):
                continue
            item = live_jobs.to_response(rows[within])
            key = f"{item.title.strip().lower()}|{item.company.name.strip().lower()}"
            if key in seen or key in platform_keys:
                continue
            seen.add(key)
            live_slice.append(item)

    window = platform_items[offset : offset + page_size]
    return window + live_slice, p_count + live_total


@router.post("/jobs", response_model=JobDetailResponse, status_code=status.HTTP_201_CREATED)
def create_job(
    payload: JobCreateRequest,
    current_user: Annotated[User, Depends(require_roles(UserRole.EMPLOYER, UserRole.ADMIN))],
    db: Annotated[Session, Depends(get_db)],
) -> JobDetailResponse:
    """Employer creates a new structured job posting."""
    # Resolve company
    company: Company | None = None
    if payload.company_id:
        company = db.scalar(
            select(Company).where(
                Company.id == payload.company_id,
                Company.created_by_user_id == current_user.id,
            )
        )
        if company is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Specified company does not belong to current employer.",
            )
    else:
        # Pick the employer's first company or auto-generate
        company = db.scalar(
            select(Company).where(Company.created_by_user_id == current_user.id).limit(1)
        )
        if company is None:
            company = Company(
                name="My Organization",
                slug=f"org-{str(current_user.id)[:8]}",
                created_by_user_id=current_user.id,
            )
            db.add(company)
            db.flush()

    family_row = None
    if payload.family and payload.family.strip():
        family_row = db.scalar(
            select(JobFamily).where(
                func.lower(JobFamily.name) == payload.family.strip().lower()
            )
        )
        if family_row is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown job family '{payload.family.strip()}'.",
            )

    new_job = Job(
        company_id=company.id,
        posted_by_user_id=current_user.id,
        family_id=family_row.id if family_row is not None else None,
        title=payload.title.strip(),
        description=payload.description.strip(),
        requirements=payload.requirements.strip() if payload.requirements else None,
        employment_type=payload.employment_type,
        experience_level=payload.experience_level,
        location=payload.location.strip(),
        is_remote=payload.is_remote,
        salary_min=payload.salary_min,
        salary_max=payload.salary_max,
        salary_currency=payload.salary_currency.upper(),
        status=JobStatus.PUBLISHED,
    )
    db.add(new_job)
    db.flush()

    # Associate required skills — via the normalizer cascade (plan §20)
    if payload.skills:
        for s_input in payload.skills:
            if not s_input.skill_name.strip():
                continue

            skill = resolve_skill(db, s_input.skill_name)

            job_skill = JobSkill(
                job_id=new_job.id,
                skill_id=skill.id,
                is_required=s_input.is_required,
                importance_weight=s_input.importance_weight,
            )
            new_job.skills.append(job_skill)

    db.commit()

    # Re-query fresh
    saved_job = db.scalar(
        select(Job)
        .options(
            selectinload(Job.company),
            selectinload(Job.family),
            selectinload(Job.skills).joinedload(JobSkill.skill),
        )
        .where(Job.id == new_job.id)
    )
    return _format_job_response(saved_job, applicant_count=0)


@router.get("/jobs", response_model=JobListResponse)
def list_jobs(
    db: Annotated[Session, Depends(get_db)],
    q: str | None = None,
    search: str | None = None,
    sort_by: str = Query(default="relevance", pattern="^(relevance|date|salary)$"),
    location: str | None = None,
    is_remote: bool | None = None,
    work_mode: WorkMode | None = None,
    employment_type: EmploymentType | None = None,
    experience_level: ExperienceLevel | None = None,
    skill: str | None = None,
    company_id: UUID | None = None,
    company: str | None = None,
    industry: str | None = None,
    family: str | None = None,
    skills: Annotated[list[str] | None, Query()] = None,
    min_salary: int | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> JobListResponse:
    """Public job search with Postgres Full-Text Search (GIN), weighted ranking, and filters.

    Plan §15/§17 filter list: company, industry, family, skills[] (AND —
    every listed skill must be present, aliases canonicalized via the
    normalizer without creating rows)."""
    query_text = (q or search or "").strip()

    query = (
        select(Job)
        .options(
            selectinload(Job.company),
            selectinload(Job.family),
            selectinload(Job.skills).joinedload(JobSkill.skill),
        )
        .where(Job.status == JobStatus.PUBLISHED)
    )

    rank_column = None
    snippet_column = None

    if query_text:
        tsquery = func.websearch_to_tsquery("english", query_text)

        match_clause = or_(
            Job.search_vector.op("@@")(tsquery),
            Job.title.ilike(f"%{query_text}%"),
            Job.description.ilike(f"%{query_text}%"),
        )
        query = query.where(match_clause)

        rank_column = func.ts_rank_cd(Job.search_vector, tsquery).label("rank_score")
        snippet_column = func.ts_headline(
            "english",
            Job.description,
            tsquery,
            "StartSel=<mark>, StopSel=</mark>, MaxWords=35, MinWords=15",
        ).label("highlight_snippet")

    if location:
        query = query.where(Job.location.ilike(f"%{location.strip()}%"))

    if is_remote is not None:
        query = query.where(Job.is_remote == is_remote)

    if employment_type:
        query = query.where(Job.employment_type == employment_type)

    if experience_level:
        query = query.where(Job.experience_level == experience_level)

    if min_salary:
        query = query.where(
            or_(Job.salary_max >= min_salary, Job.salary_min >= min_salary)
        )

    if skill:
        skill_term = f"%{skill.strip()}%"
        query = query.where(
            Job.skills.any(
                JobSkill.skill.has(Skill.name.ilike(skill_term))
            )
        )

    if company_id:
        query = query.where(Job.company_id == company_id)

    if industry:
        query = query.where(
            Job.company.has(Company.industry.ilike(f"%{industry.strip()}%"))
        )

    if company:
        query = query.where(
            Job.company.has(Company.name.ilike(f"%{company.strip()}%"))
        )

    if work_mode is not None:
        # Jobs carry only is_remote (no work_mode column): remote → is_remote;
        # hybrid/onsite → employer-location presence (documented §17 mapping).
        if work_mode == WorkMode.REMOTE:
            query = query.where(Job.is_remote.is_(True))
        else:
            query = query.where(Job.is_remote.is_(False))

    if family:
        raw_family = family.strip()
        family_row = db.scalar(
            select(JobFamily).where(func.lower(JobFamily.name) == raw_family.lower())
        )
        if family_row is None:
            try:
                family_row = db.scalar(
                    select(JobFamily).where(JobFamily.id == UUID(raw_family))
                )
            except (ValueError, TypeError, AttributeError):
                family_row = None
        # unknown family matches nothing — filter semantics, not an error
        query = query.where(Job.family_id == (family_row.id if family_row else uuid4()))

    if skills:
        # alias/fuzzy canonicalization for filter values — no row creation
        normalizer = build_db_normalizer(db)
        for raw_skill in skills:
            if not raw_skill.strip():
                continue
            canonical = normalizer.normalize(raw_skill).canonical
            query = query.where(
                Job.skills.any(
                    JobSkill.skill.has(func.lower(Skill.name) == canonical.lower())
                )
            )

    # Sorting
    if sort_by == "salary":
        query = query.order_by(
            func.coalesce(Job.salary_max, Job.salary_min, 0).desc(),
            Job.created_at.desc(),
        )
    elif sort_by == "date":
        query = query.order_by(Job.created_at.desc())
    else:  # relevance
        if query_text and rank_column is not None:
            query = query.order_by(rank_column.desc(), Job.created_at.desc())
        else:
            query = query.order_by(Job.created_at.desc())

    offset = (page - 1) * page_size

    # Live leg: keyword queries always hit Adzuna at request time; a pure
    # browse (no filters at all) fills with a default live query so the
    # catalog is never a fixed pre-loaded corpus.  Filter-only views stay on
    # the platform's own rows — the live provider only takes what+where+sort,
    # so letting it through would silently ignore precise filters.
    has_filters = any(
        [
            location,
            is_remote is not None,
            work_mode is not None,
            employment_type is not None,
            experience_level is not None,
            skill,
            company_id,
            company,
            industry,
            family,
            skills,
            min_salary,
        ]
    )
    live_query = query_text or (None if has_filters else _DEFAULT_BROWSE_QUERY)

    if live_query:
        if rank_column is not None and snippet_column is not None:
            platform_rows = db.execute(
                query.add_columns(rank_column, snippet_column).limit(_MERGE_PLATFORM_CAP)
            ).all()
            platform_items = [
                _format_job_response(
                    row[0],
                    relevance_score=round(float(row[1]) * 100, 1) if row[1] is not None else None,
                    snippet=str(row[2]) if row[2] else None,
                )
                for row in platform_rows
            ]
        else:
            platform_rows = db.scalars(query.limit(_MERGE_PLATFORM_CAP)).all()
            platform_items = [_format_job_response(j) for j in platform_rows]
        items, total = _paginate_merged(
            platform_items,
            live_query=live_query,
            live_location=location,
            sort_by=sort_by,
            offset=offset,
            page_size=page_size,
        )
    else:
        # Filter-only view: platform postings only.
        count_query = select(func.count()).select_from(query.subquery())
        total = db.scalar(count_query) or 0
        query = query.offset(offset).limit(page_size)
        jobs = db.scalars(query).all()
        items = [_format_job_response(j) for j in jobs]

    total_pages = max(1, math.ceil(total / page_size))
    return JobListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get("/jobs/nl", response_model=JobNlResponse)
def nl_search_jobs(
    db: Annotated[Session, Depends(get_db)],
    q: Annotated[str, Query(min_length=1, max_length=300)],
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> JobNlResponse:
    """NL job search (plan §15/§17): P7 → whitelist → same query builder.

    Filters are coerced/validated by Pydantic, unknown fields dropped, skills
    canonicalized through the normalizer.  Results fuse via RRF(k=60) over
    FTS order, embedding KNN order and skill-set match count (deterministic
    tie-break: recency, then id).  `parsed_filters` is echoed so the UI shows
    editable chips — the user, not the LLM, is the final authority.  Any LLM
    failure degrades to full-text search (`mode: "fts"`).
    """
    filters, mode = nl_search.parse_query(q)
    filters = nl_search.canonicalize_skills(db, filters)
    query, rank_column = nl_search.build_filtered_query(db, filters)

    if rank_column is not None:
        query = query.order_by(
            rank_column.desc(), Job.created_at.desc(), Job.id.asc()
        )
    else:
        query = query.order_by(Job.created_at.desc(), Job.id.asc())

    candidates = list(db.scalars(query.limit(nl_search.CANDIDATE_CAP)).all())
    ranked = nl_search.hybrid_rank(db, candidates, filters)
    platform_items = [_format_job_response(job) for job in ranked]

    # Live leg: the parsed keywords/skills become the Adzuna `what` query, so
    # NL search also sees real-time listings (provider failure → platform only).
    live_query = (
        " ".join(
            part
            for part in [filters.keywords or "", *list(filters.skills)[:4]]
            if part and part.strip()
        ).strip()
        or q.strip()
    )
    offset = (page - 1) * page_size
    if live_query:
        items, total = _paginate_merged(
            platform_items,
            live_query=live_query,
            live_location=filters.location,
            sort_by="relevance",
            offset=offset,
            page_size=page_size,
        )
    else:
        total = len(platform_items)
        items = platform_items[offset : offset + page_size]

    return JobNlResponse(
        items=items,
        total=total,
        mode=mode,
        parsed_filters=nl_search.parsed_filters_dict(filters),
        q=q,
    )


@router.get("/jobs/{job_id}", response_model=JobDetailResponse)
def get_job_detail(
    job_id: str,
    db: Annotated[Session, Depends(get_db)],
) -> JobDetailResponse:
    """Retrieve detailed view of a single job.

    Live Adzuna results are addressed as `adzuna-<external_id>` but have no
    detail page here — Adzuna exposes no details API, so their cards link
    straight to the provider.  A live id (or any unparseable id) is an honest
    404 rather than a path-validation 422.
    """
    if live_jobs.is_live_id(job_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Live listings open on the provider's site.",
        )
    try:
        job_uuid = UUID(job_id)
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job posting not found.",
        )

    job = db.scalar(
        select(Job)
        .options(
            selectinload(Job.company),
            selectinload(Job.family),
            selectinload(Job.skills).joinedload(JobSkill.skill),
        )
        .where(Job.id == job_uuid)
    )
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job posting not found.",
        )

    applicant_count = db.scalar(
        select(func.count(Application.id)).where(Application.job_id == job_uuid)
    ) or 0

    return _format_job_response(job, applicant_count=applicant_count)


@router.put("/jobs/{job_id}", response_model=JobDetailResponse)
def update_job(
    job_id: UUID,
    payload: JobUpdateRequest,
    current_user: Annotated[User, Depends(require_roles(UserRole.EMPLOYER, UserRole.ADMIN))],
    db: Annotated[Session, Depends(get_db)],
) -> JobDetailResponse:
    """Employer updates their job posting."""
    job = db.scalar(
        select(Job)
        .options(
            selectinload(Job.company),
            selectinload(Job.skills).joinedload(JobSkill.skill),
        )
        .where(Job.id == job_id)
    )
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job posting not found.",
        )

    if job.posted_by_user_id != current_user.id and current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to modify this job posting.",
        )

    if payload.title is not None:
        job.title = payload.title.strip()
    if payload.description is not None:
        job.description = payload.description.strip()
    if payload.requirements is not None:
        job.requirements = payload.requirements.strip() or None
    if payload.employment_type is not None:
        job.employment_type = payload.employment_type
    if payload.experience_level is not None:
        job.experience_level = payload.experience_level
    if payload.location is not None:
        job.location = payload.location.strip()
    if payload.is_remote is not None:
        job.is_remote = payload.is_remote
    if payload.salary_min is not None:
        job.salary_min = payload.salary_min
    if payload.salary_max is not None:
        job.salary_max = payload.salary_max
    if payload.salary_currency is not None:
        job.salary_currency = payload.salary_currency.upper()
    if payload.status is not None:
        job.status = payload.status
    if payload.family is not None:
        raw_family = payload.family.strip()
        if not raw_family:
            job.family_id = None  # explicit clear
        else:
            family_row = db.scalar(
                select(JobFamily).where(func.lower(JobFamily.name) == raw_family.lower())
            )
            if family_row is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Unknown job family '{raw_family}'.",
                )
            job.family_id = family_row.id

    if payload.skills is not None:
        job.skills.clear()
        db.flush()

        for s_input in payload.skills:
            if not s_input.skill_name.strip():
                continue

            skill = resolve_skill(db, s_input.skill_name)

            job_skill = JobSkill(
                job_id=job.id,
                skill_id=skill.id,
                is_required=s_input.is_required,
                importance_weight=s_input.importance_weight,
            )
            job.skills.append(job_skill)

    db.commit()

    updated_job = db.scalar(
        select(Job)
        .options(
            selectinload(Job.company),
            selectinload(Job.family),
            selectinload(Job.skills).joinedload(JobSkill.skill),
        )
        .where(Job.id == job.id)
    )
    return _format_job_response(updated_job)


@router.delete("/jobs/{job_id}", status_code=status.HTTP_200_OK)
def delete_job(
    job_id: UUID,
    current_user: Annotated[User, Depends(require_roles(UserRole.EMPLOYER, UserRole.ADMIN))],
    db: Annotated[Session, Depends(get_db)],
):
    """Employer removes or archives a job posting."""
    job = db.scalar(select(Job).where(Job.id == job_id))
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job posting not found.",
        )

    if job.posted_by_user_id != current_user.id and current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to delete this job posting.",
        )

    db.delete(job)
    db.commit()
    return {"status": "success", "message": "Job posting removed successfully."}


@router.get("/employer/jobs", response_model=list[JobDetailResponse])
def get_employer_jobs(
    current_user: Annotated[User, Depends(require_roles(UserRole.EMPLOYER, UserRole.ADMIN))],
    db: Annotated[Session, Depends(get_db)],
) -> list[JobDetailResponse]:
    """Retrieve all jobs posted by current employer with applicant metrics."""
    jobs = db.scalars(
        select(Job)
        .options(
            selectinload(Job.company),
            selectinload(Job.skills).joinedload(JobSkill.skill),
        )
        .where(Job.posted_by_user_id == current_user.id)
        .order_by(Job.created_at.desc())
    ).all()

    result: list[JobDetailResponse] = []
    for j in jobs:
        count = db.scalar(
            select(func.count(Application.id)).where(Application.job_id == j.id)
        ) or 0
        result.append(_format_job_response(j, applicant_count=count))

    return result
