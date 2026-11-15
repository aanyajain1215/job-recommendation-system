"""Heuristic trust & safety signals for the admin console.

These are *triage* signals, not verdicts. Every rule is explainable and the
returned reasons are shown verbatim to the admin so a human makes the final
call (flag / verify / take down).
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from app.models.company import Company
from app.models.job import Job
from app.models.user import User

SUSPICIOUS_JOB_THRESHOLD = 3
SUSPICIOUS_EMPLOYER_THRESHOLD = 4

# Phrases that show up disproportionately in scam / lead-gen postings.
SCAM_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\bregistration\s+fee\b", "asks for a registration fee"),
    (r"\bpay\s+(?:a\s+)?fee\b", "asks the candidate to pay a fee"),
    (r"\bsecurity\s+deposit\b", "asks for a security deposit"),
    (
        r"\b(?:pay|paid|payment|salary|wage)s?\b[^.\n]{0,40}"
        r"\b(?:bitcoin|crypto(?:currency)?|usdt|ethereum)\b",
        "crypto payment request",
    ),
    (
        r"\b(?:send|transfer|deposit)\b[^.\n]{0,30}"
        r"\b(?:bitcoin|crypto(?:currency)?|usdt)\b",
        "crypto payment request",
    ),
    (r"\b(?:gift\s*card|western\s*union|money\s*gram)\b", "untraceable payment method"),
    (r"\bno\s+(?:experience|skills?)\s+(?:needed|required)\b", "no experience required"),
    (r"\bearn\s+(?:up\s+to\s+)?\$?\s*\d", "guaranteed earnings claim"),
    (r"\b(?:whatsapp|telegram)\b", "off-platform messaging"),
    (r"\b(?:urgent|immediate)\s+(?:hiring|start)\b", "urgency pressure"),
    (r"\b(?:investment|forex|trading)\s+(?:opportunity|plan)\b", "investment scheme"),
)

CONTACT_PATTERN = re.compile(
    r"(?:\+?\d[\d\s().-]{7,}\d)|(?:[\w.+-]+@[\w-]+\.[\w.]+)|(?:https?://|www\.)",
    re.IGNORECASE,
)


def _text(job: Job) -> str:
    return f"{job.title or ''}\n{job.description or ''}\n{job.requirements or ''}".lower()


def job_signals(
    job: Job,
    *,
    company: Company | None,
    owner: User | None,
    skill_count: int,
    application_count: int,
    open_flags: int,
    native: bool = True,
) -> tuple[int, list[str]]:
    """Return (risk score, human-readable reasons) for a posting.

    Verification/ownership rules only apply to native employer postings: an
    aggregated listing has no accountable owner in our system, so penalising
    it for an unverified company would flag the entire feed.
    """
    score = 0
    reasons: list[str] = []
    description = (job.description or "").strip()

    if native:
        if company is not None and not company.is_verified:
            score += 2
            reasons.append("Company is not verified")
        if owner is not None and not owner.is_active:
            score += 3
            reasons.append("Posting owner account is deactivated")
        if owner is not None and not owner.is_verified:
            score += 1
            reasons.append("Owner account is not verified")

        # Structural completeness is only a signal when an employer controls
        # the record; aggregated feeds are sparse by design.
        if len(description) < 120:
            score += 1
            reasons.append("Very short description")

        if not (job.requirements or "").strip():
            score += 1
            reasons.append("No requirements listed")

        if skill_count == 0:
            score += 1
            reasons.append("No skills attached to the posting")

    body = _text(job)
    for pattern, label in SCAM_PATTERNS:
        if re.search(pattern, body):
            score += 3
            reasons.append(f"Scam signal: {label}")

    if native and CONTACT_PATTERN.search(description):
        score += 1
        reasons.append("Contact details inside the description")

    if job.salary_min is not None and job.salary_max is not None:
        if job.salary_min > job.salary_max:
            score += 2
            reasons.append("Salary range is inverted")
        elif job.salary_min > 0 and job.salary_max > job.salary_min * 5:
            score += 1
            reasons.append("Salary range is unusually wide")

    title = (job.title or "").strip()
    if title and (title.isupper() or "!!!" in title):
        score += 1
        reasons.append("Spammy title formatting")

    if open_flags:
        score += 3
        reasons.append(f"{open_flags} open moderation flag(s)")

    status_value = getattr(job.status, "value", job.status)
    if application_count == 0 and status_value == "published" and job.created_at:
        created = job.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        if (datetime.now(timezone.utc) - created).days > 30:
            score += 1
            reasons.append("Published for 30+ days with no applicants")

    return score, reasons


def employer_signals(
    company: Company,
    *,
    owner: User | None,
    published_jobs: int,
    application_count: int,
    flagged_jobs: int,
    open_flags: int,
    jobs_last_7d: int,
    owner_company_count: int,
    native_jobs: int,
) -> tuple[int, list[str]]:
    """Return (risk score, human-readable reasons) for a company/employer.

    Trust rules only apply once the company has posted through the platform:
    aggregated-feed companies are created by the ingest service and carry no
    accountable employer, so verification/completeness rules would flag the
    entire catalogue.
    """
    score = 0
    reasons: list[str] = []
    native = native_jobs > 0

    if native:
        if not company.is_verified:
            score += 2
            reasons.append("Company is not verified")
        if owner is not None and not owner.is_active:
            score += 4
            reasons.append("Owner account is deactivated")
        if owner is not None and not owner.is_verified:
            score += 1
            reasons.append("Owner account is not verified")

        if not (company.description or "").strip():
            score += 1
            reasons.append("No company description")
        if not (company.website or "").strip():
            score += 1
            reasons.append("No company website")

        if published_jobs >= 3 and application_count == 0:
            score += 3
            reasons.append("Posts jobs but has never received an applicant")

        if jobs_last_7d >= 5:
            score += 2
            reasons.append("Burst posting: 5+ jobs in 7 days")

        if owner_company_count > 1:
            score += 1
            reasons.append("Owner controls multiple companies")

    if flagged_jobs:
        bump = min(flagged_jobs * 2, 4)
        score += bump
        reasons.append(f"{flagged_jobs} flagged posting(s)")

    if open_flags:
        score += 3
        reasons.append(f"{open_flags} open moderation flag(s)")

    if owner_company_count > 1:
        score += 1
        reasons.append("Owner controls multiple companies")

    return score, reasons
