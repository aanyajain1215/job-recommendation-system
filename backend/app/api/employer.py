"""Employer surface (plan §E0): company profile + posting lifecycle.

Phase E0 of the employer experience. Later phases add their endpoints to
this same router:
  E1 pipeline/funnel, E2 reverse talent match, E3 insights/benchmark,
  E4 performance analytics, E5 what-if relaxer.

Ownership rules
---------------
- A company is "owned" via companies.created_by_user_id (set at register).
- A posting is "owned" via jobs.posted_by_user_id (set at create).
- ADMIN may act on any tenant, matching the rest of the API.
"""

import re
import statistics
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_current_user, require_roles
from app.api.jobs import _format_job_response
from app.core.db import get_db
from app.models.application import Application
from app.models.company import Company
from app.models.enums import ApplicationStatus, JobStatus, UserRole
from app.models.job import Job
from app.models.profile import Profile
from app.models.skill import JobSkill, ProfileSkill, Skill
from app.models.user import User
from app.schemas.employer import (
    CompanyDetailOut,
    CompanyUpdateRequest,
    DailyApplications,
    JdCheck,
    JdHealth,
    PipelineCounts,
    PostingInsightsOut,
    PostingPerformanceOut,
    PostingPipelineOut,
    PostingStatusUpdate,
    PostingTalentOut,
    SalaryBenchmark,
    SkillMarketRow,
    SkillRelaxOption,
    StageConversion,
    TalentCandidateOut,
    WhatIfOut,
    WhatIfRequest,
)
from app.schemas.job import JobDetailResponse
from app.services.embeddings import to_usd
from app.services.recommender import _ProfileContext
from app.services.scoring import score_pair

router = APIRouter(prefix="/employer", tags=["employer"])

EmployerOnly = Annotated[User, Depends(require_roles(UserRole.EMPLOYER, UserRole.ADMIN))]


def _owned_company(db: Session, user: User) -> Company:
    """The company created by this employer (one per account at register)."""
    company = db.scalar(
        select(Company)
        .where(Company.created_by_user_id == user.id)
        .order_by(Company.created_at.asc())
    )
    if company is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No company profile is associated with this account yet.",
        )
    return company


def _owned_posting(db: Session, user: User, job_id: UUID) -> Job:
    """Load a posting and enforce the employer owns it (or is ADMIN)."""
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
    if job.posted_by_user_id != user.id and user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to manage this job posting.",
        )
    return job


def _clearable(value: str | None) -> str | None:
    """'' clears an optional field; whitespace-only is treated as ''."""
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


# --------------------------------------------------------------------------- #
# Company profile
# --------------------------------------------------------------------------- #
@router.post(
    "/company",
    response_model=CompanyDetailOut,
    status_code=status.HTTP_201_CREATED,
)
def create_my_company(
    payload: CompanyUpdateRequest,
    current_user: EmployerOnly,
    db: Annotated[Session, Depends(get_db)],
) -> CompanyDetailOut:
    """Create the company profile for an employer that registered without one.

    Only offered when the account has no company yet; otherwise it would be
    ambiguous which of several companies the employer means.
    """
    existing = db.scalar(
        select(Company.id).where(Company.created_by_user_id == current_user.id)
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This account already has a company profile — edit it instead.",
        )

    if not payload.name or not payload.name.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A company name is required.",
        )

    name = payload.name.strip()
    base_slug = re.sub(r"[-\s]+", "-", re.sub(r"[^\w\s-]", "", name.lower())).strip() or "company"
    slug = f"{base_slug}-{str(current_user.id)[:8]}"

    company = Company(
        name=name,
        slug=slug,
        description=_clearable(payload.description),
        website=_clearable(payload.website),
        location=_clearable(payload.location),
        logo_url=_clearable(payload.logo_url),
        industry=_clearable(payload.industry),
        company_size=_clearable(payload.company_size),
        created_by_user_id=current_user.id,
        is_verified=False,
    )
    db.add(company)
    db.commit()
    db.refresh(company)

    out = CompanyDetailOut.model_validate(company)
    return out.model_copy(update={"open_postings": 0})


@router.get("/company", response_model=CompanyDetailOut)
def get_my_company(
    current_user: EmployerOnly,
    db: Annotated[Session, Depends(get_db)],
) -> CompanyDetailOut:
    company = _owned_company(db, current_user)
    open_postings = (
        db.scalar(
            select(func.count(Job.id)).where(
                Job.company_id == company.id,
                Job.status == JobStatus.PUBLISHED,
            )
        )
        or 0
    )
    out = CompanyDetailOut.model_validate(company)
    return out.model_copy(update={"open_postings": open_postings})


@router.put("/company", response_model=CompanyDetailOut)
def update_my_company(
    payload: CompanyUpdateRequest,
    current_user: EmployerOnly,
    db: Annotated[Session, Depends(get_db)],
) -> CompanyDetailOut:
    """Partial update: omitted/null fields stay, empty string clears."""
    company = _owned_company(db, current_user)

    if payload.name is not None:
        company.name = payload.name.strip()
    if payload.description is not None:
        company.description = _clearable(payload.description)
    if payload.website is not None:
        company.website = _clearable(payload.website)
    if payload.location is not None:
        company.location = _clearable(payload.location)
    if payload.logo_url is not None:
        company.logo_url = _clearable(payload.logo_url)
    if payload.industry is not None:
        company.industry = _clearable(payload.industry)
    if payload.company_size is not None:
        company.company_size = _clearable(payload.company_size)

    db.commit()
    db.refresh(company)
    return get_my_company(current_user=current_user, db=db)


# --------------------------------------------------------------------------- #
# Posting lifecycle
# --------------------------------------------------------------------------- #
@router.patch("/postings/{job_id}/status", response_model=JobDetailResponse)
def set_posting_status(
    job_id: UUID,
    payload: PostingStatusUpdate,
    current_user: EmployerOnly,
    db: Annotated[Session, Depends(get_db)],
) -> JobDetailResponse:
    """Publish, close, reopen (back to PUBLISHED) or archive a posting.

    Only lifecycle transitions are accepted here; content edits go through
    the existing PUT /jobs/{id} so validation stays in one place.
    """
    job = _owned_posting(db, current_user, job_id)
    job.status = payload.status
    db.commit()
    db.refresh(job)

    count = (
        db.scalar(
            select(func.count(Application.id)).where(Application.job_id == job.id)
        )
        or 0
    )
    return _format_job_response(job, applicant_count=count)


# --------------------------------------------------------------------------- #
# E1: applicant pipeline (funnel aggregates)
# --------------------------------------------------------------------------- #
@router.get("/postings/{job_id}/pipeline", response_model=PostingPipelineOut)
def get_posting_pipeline(
    job_id: UUID,
    current_user: EmployerOnly,
    db: Annotated[Session, Depends(get_db)],
) -> PostingPipelineOut:
    """Funnel counts for one posting.

    Row data (applicant names, notes, stage moves) lives on the existing
    GET /employer/jobs/{id}/applications + PATCH /employer/applications/{id}/status;
    this endpoint only aggregates so the funnel and pace render in one call.
    """
    job = _owned_posting(db, current_user, job_id)

    rows = db.execute(
        select(Application.status, func.count(Application.id))
        .where(Application.job_id == job.id)
        .group_by(Application.status)
    ).all()
    counts = {status: 0 for status in ApplicationStatus}
    for stage, count in rows:
        counts[stage] = count
    total = sum(counts.values())

    seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
    recent_7d = (
        db.scalar(
            select(func.count(Application.id)).where(
                Application.job_id == job.id,
                Application.applied_at >= seven_days_ago,
            )
        )
        or 0
    )

    days_open = max((datetime.now(timezone.utc) - job.created_at).days, 1) if job.created_at else 1

    return PostingPipelineOut(
        job_id=job.id,
        title=job.title,
        status=job.status,
        total=total,
        counts=PipelineCounts(
            applied=counts[ApplicationStatus.APPLIED],
            viewed=counts[ApplicationStatus.VIEWED],
            shortlisted=counts[ApplicationStatus.SHORTLISTED],
            interview=counts[ApplicationStatus.INTERVIEW],
            rejected=counts[ApplicationStatus.REJECTED],
            offer=counts[ApplicationStatus.OFFER],
            saved=counts[ApplicationStatus.SAVED],
        ),
        recent_7d=recent_7d,
        days_open=days_open,
        applications_per_day=round(total / days_open, 2),
    )


# --------------------------------------------------------------------------- #
# E2: reverse talent match — the seeker engine run over OWN applicants only
# --------------------------------------------------------------------------- #
@router.get("/postings/{job_id}/talent", response_model=PostingTalentOut)
def get_posting_talent(
    job_id: UUID,
    current_user: EmployerOnly,
    db: Annotated[Session, Depends(get_db)],
) -> PostingTalentOut:
    """Rank this posting's applicants with the same 8-component engine the
    candidates themselves see for the job (explainable fit, not a black box).

    Privacy boundary (plan §E2): only applicants who already applied to this
    posting are ever returned — the global job-seeker pool is not queryable
    from the employer surface. Nothing here auto-rejects: scores are assistive.
    """
    job = _owned_posting(db, current_user, job_id)

    rows = db.scalars(
        select(Application)
        .options(
            selectinload(Application.profile),
            selectinload(Application.user),
        )
        .where(Application.job_id == job.id)
        .order_by(Application.applied_at.desc())
    ).all()

    job_skills = [
        js.skill.name for js in (job.skills or []) if js.skill is not None and js.skill.name
    ]

    candidates: list[TalentCandidateOut] = []
    for app in rows:
        profile = app.profile
        if profile is None:
            continue
        try:
            # one context per profile: skills, embedding, family, salary, …
            ctx = _ProfileContext(profile)
            result = score_pair(ctx.inputs_for(job))
        except Exception:
            # a malformed profile must not sink the whole ranking
            continue

        name = f"{profile.first_name} {profile.last_name}".strip() or "Unnamed candidate"
        candidates.append(
            TalentCandidateOut(
                application_id=app.id,
                profile_id=profile.id,
                name=name,
                headline=profile.headline,
                location=profile.location,
                years_of_experience=profile.years_of_experience,
                resume_url=app.resume_url_snapshot or profile.resume_url,
                email=app.user.email if app.user else None,
                status=app.status,
                applied_at=app.applied_at,
                fit_score=result.final,
                components=result.components,
                matched_skills=result.skill_detail.matched,
                missing_required=result.skill_detail.missing_required,
                transferable=result.skill_detail.transferable,
            )
        )

    candidates.sort(key=lambda c: c.fit_score, reverse=True)

    return PostingTalentOut(
        job_id=job.id,
        title=job.title,
        total_applicants=len(rows),
        scored=len(candidates),
        job_skills=job_skills,
        candidates=candidates,
    )


def _jd_health(job) -> JdHealth:
    """Deterministic JD feedback (plan §E3/E5). Works on a real Job or on the
    duck-typed stand-in the what-if simulator builds — attribute reads only."""
    desc_len = len((job.description or "").strip())
    req_len = len((job.requirements or "").strip())
    job_skills = [js for js in (job.skills or []) if js.skill is not None and js.skill.name]
    required_count = sum(1 for js in job_skills if js.is_required)

    def _check(label: str, ok: bool, pass_detail: str, fail_detail: str) -> JdCheck:
        return JdCheck(label=label, ok=ok, detail=pass_detail if ok else fail_detail)

    checks = [
        _check(
            "Salary range",
            job.salary_min is not None and job.salary_max is not None,
            "Both bounds set — seekers can self-qualify.",
            "No salary range: qualified seekers often skip postings with invisible pay.",
        ),
        _check(
            "Description depth",
            desc_len >= 200,
            f"{desc_len} characters — enough for readers and matching.",
            f"Only {desc_len} characters — aim for 200+ so the role is concrete.",
        ),
        _check(
            "Requirements",
            req_len >= 40,
            "Requirements are spelled out.",
            "Requirements are thin (aim 40+ characters) — spell out the must-haves.",
        ),
        _check(
            "Skills tagged",
            len(job_skills) >= 3,
            f"{len(job_skills)} skills tagged — fit scoring has signal.",
            f"Only {len(job_skills)} skill(s) — tag 3+ so candidate fit scores work.",
        ),
        _check(
            "Required skills",
            required_count >= 1,
            f"{required_count} marked required.",
            "No skill marked required — mark at least one so candidates know the bar.",
        ),
        _check(
            "Job family",
            job.family_id is not None,
            "Family set — recommendations can route this posting.",
            "No job family — set one so the posting reaches the right seekers.",
        ),
        _check(
            "Title clarity",
            10 <= len(job.title) <= 70,
            f"Title ({len(job.title)} chars) is in the searchable band.",
            f"Title is {len(job.title)} chars — aim for 10-70: role + seniority, plain language.",
        ),
    ]
    return JdHealth(
        score=round(100.0 * sum(1 for c in checks if c.ok) / len(checks), 1),
        checks=checks,
    )


# --------------------------------------------------------------------------- #
# E3: insights — live JD feedback, market benchmark, supply/demand gaps
# --------------------------------------------------------------------------- #
@router.get("/postings/{job_id}/insights", response_model=PostingInsightsOut)
def get_posting_insights(
    job_id: UUID,
    current_user: EmployerOnly,
    db: Annotated[Session, Depends(get_db)],
) -> PostingInsightsOut:
    """Deterministic market intelligence for one posting (no LLM, no cost).

    - JD health: instant checklist feedback on the posting itself.
    - Benchmark: pay vs live peers in the same job family (FX-normalised USD).
    - Supply/demand: how demanded each required skill is vs how many seekers
      hold it — AGGREGATE counts only, so the talent pool stays private.
    """
    job = _owned_posting(db, current_user, job_id)

    # ---------- 1. live JD feedback ----------
    jd_health = _jd_health(job)
    job_skills = [js for js in (job.skills or []) if js.skill is not None and js.skill.name]

    # ---------- 2. market benchmark (FX-normalised USD) ----------
    family_id = job.family_id
    peers = db.scalars(
        select(Job).where(Job.status == JobStatus.PUBLISHED).where(
            Job.family_id == family_id if family_id is not None else Job.id.isnot(None)
        )
    ).all()

    peer_mins: list[float] = []
    peer_maxs: list[float] = []
    peer_mids: list[float] = []
    for p in peers:
        if p.salary_min is None or p.salary_max is None:
            continue
        lo = to_usd(p.salary_min, p.salary_currency)
        hi = to_usd(p.salary_max, p.salary_currency)
        if lo is None or hi is None:
            continue
        peer_mins.append(float(lo))
        peer_maxs.append(float(hi))
        peer_mids.append((float(lo) + float(hi)) / 2)

    my_mid: float | None = None
    if job.salary_min is not None and job.salary_max is not None:
        lo = to_usd(job.salary_min, job.salary_currency)
        hi = to_usd(job.salary_max, job.salary_currency)
        if lo is not None and hi is not None:
            my_mid = (float(lo) + float(hi)) / 2

    midpoint_percentile = None
    if my_mid is not None and peer_mids:
        below = sum(1 for m in peer_mids if m <= my_mid)
        midpoint_percentile = round(100.0 * below / len(peer_mids), 1)

    remote_share = (
        round(sum(1 for p in peers if p.is_remote) / len(peers), 3) if peers else None
    )

    benchmark: SalaryBenchmark | None = None
    if peer_mids or remote_share is not None:
        benchmark = SalaryBenchmark(
            family=job.family.name if job.family is not None else None,
            peer_jobs=len(peers),
            median_min_usd=round(statistics.median(peer_mins), 2) if peer_mins else None,
            median_max_usd=round(statistics.median(peer_maxs), 2) if peer_maxs else None,
            midpoint_percentile=midpoint_percentile,
            remote_share=remote_share,
        )

    # ---------- 3. supply / demand (aggregate only) ----------
    demand_all = {
        name: count
        for name, count in db.execute(
            select(Skill.name, func.count(func.distinct(Job.id)))
            .join(JobSkill, JobSkill.skill_id == Skill.id)
            .join(Job, Job.id == JobSkill.job_id)
            .where(Job.status == JobStatus.PUBLISHED, JobSkill.is_required.is_(True))
            .group_by(Skill.name)
        ).all()
    }

    demand_source = demand_all
    if family_id is not None:
        family_demand = {
            name: count
            for name, count in db.execute(
                select(Skill.name, func.count(func.distinct(Job.id)))
                .join(JobSkill, JobSkill.skill_id == Skill.id)
                .join(Job, Job.id == JobSkill.job_id)
                .where(
                    Job.status == JobStatus.PUBLISHED,
                    JobSkill.is_required.is_(True),
                    Job.family_id == family_id,
                )
                .group_by(Skill.name)
            ).all()
        }
        # fall back to the whole market when the family slice is empty
        demand_source = family_demand or demand_all

    supply = {
        name: count
        for name, count in db.execute(
            select(Skill.name, func.count(ProfileSkill.profile_id))
            .join(ProfileSkill, ProfileSkill.skill_id == Skill.id)
            .group_by(Skill.name)
        ).all()
    }

    def _row(skill: str, demand: int) -> SkillMarketRow:
        held = supply.get(skill, 0)
        return SkillMarketRow(
            skill=skill, jobs_requiring=demand, seekers_holding=held, gap=demand - held
        )

    required_skill_market = sorted(
        (
            _row(js.skill.name, demand_source.get(js.skill.name, 0))
            for js in job_skills
            if js.is_required
        ),
        key=lambda r: r.gap,
        reverse=True,
    )

    family_top_demand = [
        _row(name, count)
        for name, count in sorted(demand_source.items(), key=lambda kv: kv[1], reverse=True)[:8]
    ]

    return PostingInsightsOut(
        job_id=job.id,
        title=job.title,
        jd_health=jd_health,
        benchmark=benchmark,
        required_skill_market=required_skill_market,
        family_top_demand=family_top_demand,
    )


# --------------------------------------------------------------------------- #
# E4: performance analytics — time series, conversion, pipeline health
# --------------------------------------------------------------------------- #
@router.get("/postings/{job_id}/performance", response_model=PostingPerformanceOut)
def get_posting_performance(
    job_id: UUID,
    current_user: EmployerOnly,
    db: Annotated[Session, Depends(get_db)],
) -> PostingPerformanceOut:
    """Deterministic funnel analytics for one posting: a 30-day application
    series, stage-conversion rates, and a coarse pipeline-health label."""
    job = _owned_posting(db, current_user, job_id)

    total = (
        db.scalar(select(func.count(Application.id)).where(Application.job_id == job.id)) or 0
    )

    # ---------- 30-day series (UTC calendar days, zero-filled) ----------
    today = datetime.now(timezone.utc).date()
    first_day = today - timedelta(days=29)
    cutoff_dt = datetime.combine(first_day, datetime.min.time(), tzinfo=timezone.utc)
    by_day = {
        str(day): count
        for day, count in db.execute(
            select(func.date(Application.applied_at), func.count(Application.id))
            .where(
                Application.job_id == job.id,
                Application.applied_at >= cutoff_dt,
            )
            .group_by(func.date(Application.applied_at))
        ).all()
    }
    series = []
    for i in range(30):
        day = (first_day + timedelta(days=i)).isoformat()
        series.append(DailyApplications(date=day, count=by_day.get(day, 0)))

    # ---------- stage conversion ----------
    status_counts = dict(
        db.execute(
            select(Application.status, func.count(Application.id))
            .where(Application.job_id == job.id)
            .group_by(Application.status)
        ).all()
    )

    def _cnt(*statuses: ApplicationStatus) -> int:
        return sum(int(status_counts.get(s, 0)) for s in statuses)

    def _rate(n: int) -> float:
        return round(100.0 * n / total, 1) if total else 0.0

    conversion = StageConversion(
        viewed_rate=_rate(_cnt(ApplicationStatus.VIEWED, ApplicationStatus.SHORTLISTED,
                               ApplicationStatus.INTERVIEW, ApplicationStatus.OFFER)),
        shortlist_rate=_rate(_cnt(ApplicationStatus.SHORTLISTED, ApplicationStatus.INTERVIEW,
                                  ApplicationStatus.OFFER)),
        interview_rate=_rate(_cnt(ApplicationStatus.INTERVIEW, ApplicationStatus.OFFER)),
        offer_rate=_rate(_cnt(ApplicationStatus.OFFER)),
        rejection_rate=_rate(_cnt(ApplicationStatus.REJECTED)),
    )

    # ---------- freshness + pace ----------
    recent_7d = (
        db.scalar(
            select(func.count(Application.id)).where(
                Application.job_id == job.id,
                Application.applied_at >= datetime.now(timezone.utc) - timedelta(days=7),
            )
        )
        or 0
    )

    last_applied = db.scalar(
        select(func.max(Application.applied_at)).where(Application.job_id == job.id)
    )
    days_since_last = (
        max((datetime.now(timezone.utc) - last_applied).days, 0) if last_applied else None
    )

    # ---------- avg days from apply → latest stage change (moved only) ----------
    acted = db.scalars(
        select(Application).where(
            Application.job_id == job.id,
            Application.status.in_(
                [
                    ApplicationStatus.VIEWED,
                    ApplicationStatus.SHORTLISTED,
                    ApplicationStatus.INTERVIEW,
                    ApplicationStatus.OFFER,
                    ApplicationStatus.REJECTED,
                ]
            ),
        )
    ).all()
    avg_days_to_last_move = None
    if acted:
        deltas = [(a.updated_at - a.applied_at).total_seconds() / 86400 for a in acted]
        avg_days_to_last_move = round(sum(deltas) / len(deltas), 1)

    # ---------- coarse health label ----------
    if total == 0:
        health = "idle"
    elif recent_7d >= 3:
        health = "hot"
    elif recent_7d >= 1:
        health = "steady"
    else:
        health = "stale"

    return PostingPerformanceOut(
        job_id=job.id,
        title=job.title,
        total=total,
        series=series,
        conversion=conversion,
        recent_7d=recent_7d,
        days_since_last_application=days_since_last,
        avg_days_to_last_move=avg_days_to_last_move,
        health=health,
    )


# --------------------------------------------------------------------------- #
# E5: what-if relaxer — simulate loosening constraints; never auto-applies
# --------------------------------------------------------------------------- #
def _lvl_value(value) -> str:
    """Plain string for ExperienceLevel (or anything else) in copy."""
    return str(getattr(value, "value", value))


def _seeker_reach(db: Session, required: list[str]) -> tuple[int, int]:
    """(reach, total_seekers): seeker profiles holding EVERY required skill.

    Aggregate counts only — who holds a skill is never exposed (plan §E2/E5).
    """
    total = (
        db.scalar(
            select(func.count(Profile.id))
            .join(User, User.id == Profile.user_id)
            .where(User.role == UserRole.JOB_SEEKER)
        )
        or 0
    )
    if not required:
        return total, total
    rows = db.execute(
        select(ProfileSkill.profile_id, Skill.name)
        .join(Skill, Skill.id == ProfileSkill.skill_id)
        .join(Profile, Profile.id == ProfileSkill.profile_id)
        .join(User, User.id == Profile.user_id)
        .where(User.role == UserRole.JOB_SEEKER, Skill.name.in_(required))
    ).all()
    holders: dict[str, set] = {}
    for profile_id, name in rows:
        holders.setdefault(name, set()).add(profile_id)
    sets = [holders.get(name, set()) for name in required]
    return len(set.intersection(*sets)), total


@router.post("/postings/{job_id}/whatif", response_model=WhatIfOut)
def simulate_posting_relaxation(
    job_id: UUID,
    current_user: EmployerOnly,
    db: Annotated[Session, Depends(get_db)],
    payload: WhatIfRequest | None = None,
) -> WhatIfOut:
    """Simulate relaxing this posting's constraints (plan §E5).

    Before/after for three things:
    - market reach: AGGREGATE count of seeker profiles holding all required
      skills (pool stays private — counts only)
    - avg fit of the employer's OWN applicants under the simulated posting
      (same 8-component engine, run against a duck-typed stand-in job)
    - JD health score

    Plus ranked single-skill "biggest lever" options. The posting row is
    NEVER modified here — the employer applies the change explicitly via
    PUT /jobs/{id}.
    """
    payload = payload or WhatIfRequest()
    job = _owned_posting(db, current_user, job_id)

    # ---- validate the requested relaxation against the posting ----
    required_rows = [
        js for js in (job.skills or []) if js.skill is not None and js.is_required
    ]
    canonical = [js.skill.name for js in required_rows]
    drop_set = {d.strip().lower() for d in payload.drop_required_skills if d and d.strip()}
    unknown = drop_set - {c.lower() for c in canonical}
    if unknown:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Not required skills on this posting: {', '.join(sorted(unknown))}",
        )
    eff_min = payload.salary_min if payload.salary_min is not None else job.salary_min
    eff_max = payload.salary_max if payload.salary_max is not None else job.salary_max
    if eff_min is not None and eff_max is not None and eff_min > eff_max:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "salary_min cannot exceed salary_max"
        )

    # ---- simulated posting: a duck-typed stand-in, so the real Job row is
    # never mutated (nothing can leak into the database) ----
    sim_skills = [
        SimpleNamespace(
            skill=js.skill,
            is_required=bool(js.is_required) and js.skill.name.lower() not in drop_set,
            importance_weight=float(js.importance_weight or 1.0),
        )
        for js in (job.skills or [])
        if js.skill is not None
    ]
    sim_job = SimpleNamespace(
        skills=sim_skills,
        family=job.family,
        family_id=job.family_id,
        embedding=job.embedding,
        salary_min=eff_min,
        salary_max=eff_max,
        salary_currency=job.salary_currency,
        experience_level=(
            payload.experience_level
            if payload.experience_level is not None
            else job.experience_level
        ),
        is_remote=job.is_remote if payload.is_remote is None else payload.is_remote,
        location=job.location,
        title=job.title,
        description=job.description,
        requirements=job.requirements,
    )
    after_canonical = [c for c in canonical if c.lower() not in drop_set]

    # ---- market reach (aggregate counts only) ----
    reach_before, total_seekers = _seeker_reach(db, canonical)
    reach_after, _ = _seeker_reach(db, after_canonical)

    # ---- own applicants: fit before / after (one profile context each) ----
    app_rows = db.scalars(
        select(Application)
        .options(selectinload(Application.profile))
        .where(Application.job_id == job.id)
    ).all()
    fit_before: list[float] = []
    fit_after: list[float] = []
    for app in app_rows:
        profile = app.profile
        if profile is None:
            continue
        try:
            ctx = _ProfileContext(profile)
            fit_before.append(score_pair(ctx.inputs_for(job)).final)
            fit_after.append(score_pair(ctx.inputs_for(sim_job)).final)
        except Exception:
            continue
    avg_before = round(sum(fit_before) / len(fit_before), 1) if fit_before else None
    avg_after = round(sum(fit_after) / len(fit_after), 1) if fit_after else None

    # ---- JD health under the simulated posting ----
    health_before = _jd_health(job)
    health_after = _jd_health(sim_job)

    # ---- biggest single-skill levers (gain relative to simulated state) ----
    drop_options: list[SkillRelaxOption] = []
    for name in after_canonical:
        reach_if, _ = _seeker_reach(db, [x for x in after_canonical if x != name])
        drop_options.append(
            SkillRelaxOption(
                skill=name, reach_if_dropped=reach_if, gain=reach_if - reach_after
            )
        )
    drop_options.sort(key=lambda o: o.gain, reverse=True)

    # ---- human-readable effects ----
    is_baseline = (
        not drop_set
        and payload.experience_level is None
        and payload.is_remote is None
        and payload.salary_min is None
        and payload.salary_max is None
    )
    effects: list[str] = []
    if drop_set:
        delta = reach_after - reach_before
        if delta > 0:
            effects.append(
                f"Market reach grows {reach_before} → {reach_after} "
                f"(+{delta} seeker profiles hold the remaining required skills)."
            )
        elif delta == 0:
            effects.append(
                "Market reach is unchanged — those skills aren't the bottleneck "
                "(everyone who holds the rest already holds them)."
            )
        else:  # mathematically unreachable; kept defensive
            effects.append(f"Market reach moves {reach_before} → {reach_after}.")
    if avg_before is not None and avg_after is not None and avg_before != avg_after:
        direction = "rises" if avg_after > avg_before else "falls"
        plural = "" if len(fit_after) == 1 else "s"
        effects.append(
            f"Average fit of your {len(fit_after)} scored applicant{plural} "
            f"{direction} {avg_before} → {avg_after}."
        )
    if health_after.score != health_before.score:
        effects.append(
            f"JD health {health_before.score}% → {health_after.score}% "
            f"({'improves' if health_after.score > health_before.score else 'drops'} "
            "under this change)."
        )
    if payload.experience_level is not None and payload.experience_level != job.experience_level:
        effects.append(
            f"Experience level {_lvl_value(job.experience_level)} → "
            f"{_lvl_value(payload.experience_level)}: the experience component "
            "changes for every applicant."
        )
    if payload.is_remote is not None and payload.is_remote != job.is_remote:
        effects.append(
            "Remote flag flips: the location component changes for every applicant."
        )
    if (payload.salary_min is not None or payload.salary_max is not None) and (
        eff_min != job.salary_min or eff_max != job.salary_max
    ):
        effects.append(
            f"Pay band changes to {eff_min} – {eff_max} {job.salary_currency}: "
            "the salary component changes for every applicant."
        )
    if not effects:
        effects.append(
            "Baseline: this IS the current posting — toggle a relaxation to see its effect."
            if is_baseline
            else "No measurable change from this combination."
        )

    return WhatIfOut(
        job_id=job.id,
        title=job.title,
        applied=payload,
        reach_before=reach_before,
        reach_after=reach_after,
        total_seekers=total_seekers,
        applicants_scored=len(fit_after),
        avg_fit_before=avg_before,
        avg_fit_after=avg_after,
        jd_health_before=health_before.score,
        jd_health_after=health_after.score,
        drop_options=drop_options,
        effects=effects,
    )


@router.post(
    "/postings/{job_id}/duplicate",
    response_model=JobDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
def duplicate_posting(
    job_id: UUID,
    current_user: EmployerOnly,
    db: Annotated[Session, Depends(get_db)],
) -> JobDetailResponse:
    """Clone a posting (content + required skills) as a new DRAFT.

    Clones land in DRAFT so the employer reviews them before publishing —
    a published clone would instantly reappear in job-seeker feeds.
    """
    src = _owned_posting(db, current_user, job_id)

    copy = Job(
        company_id=src.company_id,
        posted_by_user_id=current_user.id,
        family_id=src.family_id,
        title=f"{src.title} (copy)"[:200],
        description=src.description,
        requirements=src.requirements,
        employment_type=src.employment_type,
        experience_level=src.experience_level,
        location=src.location,
        is_remote=src.is_remote,
        salary_min=src.salary_min,
        salary_max=src.salary_max,
        salary_currency=src.salary_currency,
        status=JobStatus.DRAFT,
        # never inherit source/external identity: the clone is a native post
        source="native",
        external_id=None,
        external_url=None,
    )
    db.add(copy)
    db.flush()

    for js in src.skills or []:
        db.add(
            JobSkill(
                job_id=copy.id,
                skill_id=js.skill_id,
                is_required=js.is_required,
                importance_weight=js.importance_weight,
            )
        )
    db.commit()

    created = _owned_posting(db, current_user, copy.id)
    return _format_job_response(created, applicant_count=0)
