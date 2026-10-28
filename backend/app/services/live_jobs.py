"""Query-time live jobs — Adzuna fetched when the user searches, never pre-loaded.

The platform's job corpus is *not* ingested: employers post their own
listings (native rows), and every keyword search additionally hits Adzuna in
real time.  Live results are transient — mapped to response shapes (and, for
the recommendation feed, to ephemeral ORM stand-ins) without ever writing a
Job/Company row.  Cards link straight to the provider's posting.

Shares the deterministic structurer with the offline pipeline
(`app.services.ingest.structure`) so skill extraction and family assignment
are identical wherever a posting is seen.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone
from functools import lru_cache
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.company import Company
from app.models.enums import JobStatus
from app.models.job import Job
from app.models.job_family import JobFamily
from app.models.skill import JobSkill, Skill
from app.models.profile import Profile
from app.schemas.job import JobDetailResponse, JobSkillRequirement
from app.schemas.user import CompanySummary
from app.services.ingest import (
    assign_family,
    clean_text,
    detect_employment_type,
    detect_remote,
    extract_skills,
    load_families,
    load_surface_pairs,
    map_seniority,
    parse_location,
    parse_salary,
    parse_years,
    resolve_currency,
)
from app.services.ingest.fetch import fetch_adzuna_search

log = logging.getLogger(__name__)

# Live items are addressed as `adzuna-<external_id>` — Adzuna exposes no
# details endpoint, so list cards link out to the provider instead of routing
# through /jobs/{id}.
LIVE_PREFIX = "adzuna-"

# Identical queries within the TTL are served from memory (double-mounts,
# pagination back-and-forth) — still "live", just not wastefully so.
_CACHE_TTL_SECONDS = 120.0
_CACHE_MAX_ENTRIES = 200
_search_cache: dict[tuple, tuple[float, list[dict], int]] = {}

# Search latency budget: degrade to platform-only rather than hang the page.
LIVE_TIMEOUT_SECONDS = 8.0

# Sort mapping → Adzuna's own `sort_by` (None = provider best-match).
_ADZUNA_SORT = {"date": "date", "salary": "salary"}


def is_live_id(job_id: str | None) -> bool:
    return bool(job_id) and str(job_id).startswith(LIVE_PREFIX)


def live_id(external_id: str) -> str:
    return f"{LIVE_PREFIX}{external_id}"


@lru_cache(maxsize=1)
def _surface_pairs() -> list[tuple[str, str]]:
    return load_surface_pairs()


@lru_cache(maxsize=1)
def _families() -> list[dict]:
    return load_families()


def _parse_posted_at(raw: str | None) -> datetime:
    text = (raw or "").strip()
    if text:
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def _map_posting(raw: dict) -> dict | None:
    """Raw Adzuna row → normalized posting (pipeline stages 2–4, no I/O).

    Returns None for junk rows (empty title / stub description) so quality
    stays comparable with the gated pipeline output.
    """
    title = clean_text(raw.get("title")) or ""
    description = clean_text(raw.get("description")) or ""
    if not title or len(description) < 40:
        return None

    # Salary: explicit bounds win; otherwise the same text parser as ingest.
    emin, emax = raw.get("salary_min"), raw.get("salary_max")
    if emin is not None or emax is not None:
        salary_min = int(emin) if emin is not None else None
        salary_max = int(emax) if emax is not None else None
        if salary_min is not None and salary_max is not None and salary_min > salary_max:
            salary_min, salary_max = salary_max, salary_min
        salary_currency = resolve_currency("adzuna")
    else:
        salary_min, salary_max, salary_currency = parse_salary(
            title, default_currency=resolve_currency("adzuna")
        )

    raw_location = str(raw.get("location") or "").strip()
    location = parse_location(raw_location) or raw_location or "Not specified"
    years = parse_years(description)
    level = map_seniority(title, years)
    remote = bool(raw.get("is_remote")) or detect_remote(title, description, location)
    employment = detect_employment_type(f"{title} {description[:400]}")

    skills = extract_skills(title, description, _surface_pairs())
    family = assign_family(title, _families())

    return {
        "source": "adzuna",
        "external_id": str(raw.get("external_id") or ""),
        "title": title,
        "description": description,
        "company": str(raw.get("company") or "Unknown"),
        "location": location[:150],
        "is_remote": remote,
        "salary_min": salary_min,
        "salary_max": salary_max,
        "currency": salary_currency or "USD",
        "url": str(raw.get("url") or ""),
        "created_at": _parse_posted_at(raw.get("posted_at")),
        "employment_type": employment,
        "experience_level": level,
        "skills": skills,
        "family": family,
    }


def search_postings(
    query: str,
    *,
    location: str | None = None,
    page: int = 1,
    page_size: int = 20,
    sort_by: str | None = None,
) -> tuple[list[dict], int]:
    """Live Adzuna search → (normalized postings, total match count).

    Never raises: provider/network failures log and return ([], 0) so the
    caller degrades to platform postings alone.  Adzuna effectively ANDs the
    terms of `what`, so a long query that matches nothing is retried once
    with its first three words (recall rescue, still this query's results).
    """
    key = (query.strip().lower(), (location or "").strip().lower(), page, page_size, sort_by)
    cached = _search_cache.get(key)
    if cached is not None and time.monotonic() - cached[0] < _CACHE_TTL_SECONDS:
        return cached[1], cached[2]

    def _fetch(what: str) -> tuple[list[dict], int]:
        return fetch_adzuna_search(
            what,
            page=page,
            results_per_page=page_size,
            where=location or None,
            sort_by=_ADZUNA_SORT.get(sort_by or "relevance"),
            timeout=LIVE_TIMEOUT_SECONDS,
        )

    try:
        rows, total = _fetch(query)
        tokens = query.split()
        if total == 0 and len(tokens) > 3:
            rows, total = _fetch(" ".join(tokens[:3]))
    except Exception:  # noqa: BLE001 - live leg must never break the page
        log.warning("live Adzuna search failed for %r; serving platform-only", query)
        return [], 0

    postings: list[dict] = []
    seen: set[str] = set()
    for raw in rows:
        posting = _map_posting(raw)
        if posting is None or not posting["external_id"]:
            continue
        if posting["external_id"] in seen:
            continue
        seen.add(posting["external_id"])
        postings.append(posting)

    if len(_search_cache) >= _CACHE_MAX_ENTRIES:
        _search_cache.clear()
    _search_cache[key] = (time.monotonic(), postings, total)
    return postings, total


def _company_summary(name: str) -> CompanySummary:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:48] or "company"
    return CompanySummary(
        id=uuid5(NAMESPACE_URL, f"adzuna:company:{name}"),
        name=name,
        slug=slug,
    )


def to_response(
    posting: dict,
    *,
    relevance_score: float | None = None,
    snippet: str | None = None,
) -> JobDetailResponse:
    """Mapped posting → list/detail response item (transient, never persisted)."""
    return JobDetailResponse(
        id=live_id(posting["external_id"]),
        company_id=None,
        posted_by_user_id=None,
        title=posting["title"],
        description=posting["description"],
        requirements=None,
        employment_type=posting["employment_type"],
        experience_level=posting["experience_level"],
        location=posting["location"],
        is_remote=posting["is_remote"],
        salary_min=posting["salary_min"],
        salary_max=posting["salary_max"],
        salary_currency=posting["currency"],
        status=JobStatus.PUBLISHED,
        created_at=posting["created_at"],
        updated_at=posting["created_at"],
        company=_company_summary(posting["company"]),
        skills=[
            JobSkillRequirement(
                skill_name=name,
                category=None,
                is_required=is_required,
                importance_weight=1.0,
            )
            for name, is_required in posting["skills"]
        ],
        applicant_count=0,
        relevance_score=relevance_score,
        snippet=snippet,
        family=posting["family"],
        project_relevance=None,
        external_url=posting["url"],
        source="adzuna",
    )


def transient_job(db: Session, posting: dict) -> Job:
    """Ephemeral ORM stand-in so the 8-component scorer can rank live results.

    Every related object is built transient (never `db.add`ed): the row and
    its company/family/skill graph exist only for this request, so nothing
    about a live search ever lands in the database.
    """
    company = Company(
        id=uuid5(NAMESPACE_URL, f"adzuna:company:{posting['company']}"),
        name=posting["company"],
        slug=re.sub(r"[^a-z0-9]+", "-", posting["company"].lower()).strip("-")[:48]
        or "company",
        # Transient rows never see the DB's server defaults — a NULL here
        # would poison CompanySummary(is_verified: bool).
        is_verified=False,
    )

    family: JobFamily | None = None
    family_name = posting.get("family")
    if family_name:
        row = db.scalar(
            select(JobFamily).where(func.lower(JobFamily.name) == family_name.lower())
        )
        if row is not None:
            # Transient *copy* of the canonical row — assigning the persistent
            # row itself would cascade this transient Job into the session.
            family = JobFamily(id=row.id, name=row.name, parent_id=row.parent_id)

    job = Job(
        id=live_id(posting["external_id"]),
        source="adzuna",
        external_id=posting["external_id"],
        external_url=posting["url"],
        title=posting["title"],
        description=posting["description"],
        requirements=None,
        employment_type=posting["employment_type"],
        experience_level=posting["experience_level"],
        location=posting["location"],
        is_remote=posting["is_remote"],
        salary_min=posting["salary_min"],
        salary_max=posting["salary_max"],
        salary_currency=posting["currency"],
        status=JobStatus.PUBLISHED,
        created_at=posting["created_at"],
        updated_at=posting["created_at"],
    )
    job.company = company
    # SQLAlchemy does not back-propagate the FK on a transient instance — set
    # it explicitly so fallbacks that read job.company_id never see None.
    job.company_id = company.id
    job.family = family
    job.skills = [
        JobSkill(
            skill=Skill(name=name, category=None),
            is_required=is_required,
            importance_weight=1.0,
        )
        for name, is_required in posting["skills"]
    ]
    job.applications = []
    return job


def profile_live_query(profile: Profile) -> str:
    """Short Adzuna-friendly query derived from the seeker's profile.

    `_profile_query_text` (built for Postgres FTS) is far too rich for
    Adzuna: its `what` effectively ANDs every term, so bio prose or a
    location string collapses recall to zero.  Keep one tight candidate —
    target role → headline → top skills — capped at three words (the same
    bound as the proven ingest rotation queries).
    """
    candidates: list[str] = []
    try:
        target = getattr(profile, "target_family", None)
        if target is not None and target.name:
            candidates.append(str(target.name))
    except Exception:  # noqa: BLE001 - detached profile in some flows
        pass
    headline = (profile.headline or "").split("|")[0].strip()
    if headline:
        candidates.append(headline)
    skills = [
        ps.skill.name
        for ps in (profile.skills or [])
        if ps.skill is not None and ps.skill.name
    ]
    if skills:
        candidates.append(" ".join(skills[:2]))

    for candidate in candidates:
        query = " ".join(candidate.split()[:3]).strip()
        if query:
            return query
    return ""


def live_candidates(db: Session, profile: Profile, limit: int) -> list[Job]:
    """Profile-derived live Adzuna candidates for the recommendation feed.

    Uses a tight role query (see profile_live_query), so the feed stays
    personal while the corpus stays query-time-only.
    """
    query = profile_live_query(profile)
    if not query:
        return []
    postings, _total = search_postings(
        query, page=1, page_size=max(min(limit, 25), 10)
    )
    return [transient_job(db, p) for p in postings[:limit]]
