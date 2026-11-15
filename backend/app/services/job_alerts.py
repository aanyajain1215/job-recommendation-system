"""Saved-job alerts: matching, digest creation, and delivery orchestration.

Design notes
------------
* **Seed set** — the jobs a seeker has explicitly saved
  (``applications.status = 'saved'``).  Un-saving deletes that row, so the
  seed set never carries stale historical ``SAVE`` interactions.
* **Similarity** — each candidate job is scored against each saved job with
  the existing deterministic ``scoring.score_pair`` engine, using alert-
  specific weights.  A title-similarity bonus (RapidFuzz) is blended in.
  The best saved job wins and becomes the match's explanation anchor.
* **Newness** — candidates are published jobs created after the previous
  digest (or a 24h lookback on the first run).  Jobs the user already saved,
  applied to, or was already alerted about are excluded.
* **Dedupe** — ``job_alert_items`` has a unique ``(user_id, job_id)``
  constraint, so a job is only ever alerted once per user.
"""

from __future__ import annotations

import html
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from uuid import UUID

import numpy as np
from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings
from app.models.alerts import JobAlert, JobAlertDigest, JobAlertItem, Notification
from app.models.application import Application
from app.models.enums import ApplicationStatus, ExperienceLevel, JobStatus, ProficiencyLevel
from app.models.job import Job
from app.models.profile import Profile
from app.models.skill import JobSkill
from app.models.user import User
from app.services.email_delivery import send_email
from app.services.scoring import (
    ComponentInputs,
    JobSkillReq,
    semantic_similarity,
    score_pair,
)
from app.services.skill_graph import load_seed_graph, transfer_similarity

log = logging.getLogger(__name__)

# Saved-job similarity weights (education/project deliberately excluded:
# a saved job is not a person and has no degree or project history).
ALERT_WEIGHTS: dict[str, float] = {
    "semantic": 0.40,
    "skill": 0.30,
    "interest": 0.10,
    "experience": 0.05,
    "location": 0.05,
    "salary": 0.05,
    "education": 0.00,
    "project": 0.00,
}

# Gate: a candidate must share at least one strong signal with the seed.
SEMANTIC_GATE = 45.0
SKILL_GATE = 40.0
TITLE_GATE = 65.0

# Representative years for a saved job's seniority band.
_LEVEL_YEARS: dict[ExperienceLevel, float] = {
    ExperienceLevel.ENTRY: 1.0,
    ExperienceLevel.MID: 3.5,
    ExperienceLevel.SENIOR: 6.5,
    ExperienceLevel.LEAD: 10.0,
    ExperienceLevel.EXECUTIVE: 12.0,
}

_DAILY_SECONDS = 86400
_WEEKLY_SECONDS = 7 * _DAILY_SECONDS


@dataclass
class AlertMatch:
    """One matched candidate job and the saved job that seeded it."""

    job: Job
    seed_job: Job
    score: float
    reason: str
    matched_skills: list[str] = field(default_factory=list)


@dataclass
class AlertScanResult:
    items: list[AlertMatch]
    seeds_used: int
    candidates_scanned: int


@dataclass
class _SeedContext:
    job: Job
    requirements: list[JobSkillReq]
    possessed: set[str]
    seeker_skills: dict[str, tuple[ProficiencyLevel | None, float | None]]
    family: str | None
    family_parent: UUID | None
    embedding: np.ndarray | None
    years: float | None
    salary_min: int | None
    salary_max: int | None
    transfer_cache: dict[str, float | None] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Input helpers
# ---------------------------------------------------------------------------

def _job_requirements(job: Job) -> list[JobSkillReq]:
    reqs: list[JobSkillReq] = []
    for js in job.skills or []:
        if js.skill is None or not js.skill.name:
            continue
        reqs.append(
            JobSkillReq(
                name=js.skill.name,
                category=js.skill.category,
                is_required=bool(js.is_required),
                importance_weight=float(js.importance_weight or 1.0),
            )
        )
    return reqs


def _family_parts(job: Job) -> tuple[str | None, UUID | None]:
    try:
        family = job.family
    except Exception:  # detached instance in a test
        return None, None
    if family is None:
        return None, None
    return family.name, family.parent_id


def _embedding(job: Job) -> np.ndarray | None:
    if not job.embedding:
        return None
    try:
        return np.asarray(job.embedding, dtype=np.float32)
    except Exception:
        return None


def _cosine(left: np.ndarray | None, right: np.ndarray | None) -> float | None:
    if left is None or right is None:
        return None
    denom = float(np.linalg.norm(left) * np.linalg.norm(right))
    if denom <= 0:
        return None
    return float(np.dot(left, right) / denom)


def _seed_context(job: Job) -> _SeedContext:
    requirements = _job_requirements(job)
    possessed = {
        req.name.lower().strip()
        for req in requirements
        if req.name and req.name.strip()
    }
    family, family_parent = _family_parts(job)
    return _SeedContext(
        job=job,
        requirements=requirements,
        possessed=possessed,
        seeker_skills={name: (ProficiencyLevel.ADVANCED, None) for name in possessed},
        family=family,
        family_parent=family_parent,
        embedding=_embedding(job),
        years=_LEVEL_YEARS.get(job.experience_level),
        salary_min=job.salary_min,
        salary_max=job.salary_max,
    )


def _transfers_for(seed: _SeedContext, requirements: list[JobSkillReq]) -> dict[str, float]:
    """Transfer credit for candidate skills the saved job does not literally list."""
    transfers: dict[str, float] = {}
    if not seed.possessed:
        return transfers
    graph = load_seed_graph()
    for req in requirements:
        key = req.name.lower().strip()
        if not key or key in seed.possessed:
            continue
        if key not in seed.transfer_cache:
            seed.transfer_cache[key] = transfer_similarity(graph, seed.possessed, req.name)
        sim = seed.transfer_cache[key]
        if sim is not None:
            transfers[key] = sim
    return transfers


def _similarity_against_seed(
    seed: _SeedContext,
    candidate: Job,
    candidate_requirements: list[JobSkillReq],
    title_weight: float,
) -> tuple[float, str, list[str]] | None:
    """Score one candidate against one saved job.

    Returns ``(final_score, reason, matched_skills)`` or ``None`` when the
    pair fails the strong-signal gate.  The caller blends and compares seeds.
    """
    candidate_family, candidate_parent = _family_parts(candidate)
    same_family = bool(
        seed.family
        and candidate_family
        and seed.family.strip().lower() == candidate_family.strip().lower()
    )
    distance = None
    if seed.family and candidate_family and seed.family_parent and seed.family_parent == candidate_parent:
        distance = 1

    cosine = _cosine(seed.embedding, _embedding(candidate))
    inputs = ComponentInputs(
        semantic_cosine=cosine,
        seeker_skills=seed.seeker_skills,
        job_skills=candidate_requirements,
        transfer_similarities=_transfers_for(seed, candidate_requirements),
        years_of_experience=seed.years,
        job_level=candidate.experience_level,
        seeker_project_skills=set(seed.possessed),
        job_is_remote=bool(candidate.is_remote),
        seeker_location=seed.job.location,
        job_location=candidate.location,
        seeker_preferred_locations={seed.job.location.strip().lower()} if seed.job.location else set(),
        seeker_open_to_remote=bool(seed.job.is_remote),
        seeker_salary_min=seed.salary_min,
        seeker_salary_max=seed.salary_max,
        job_salary_min=candidate.salary_min,
        job_salary_max=candidate.salary_max,
        seeker_target_family=seed.family,
        job_family=candidate_family,
        family_graph_distance=distance,
        seeker_interest_skills=set(seed.possessed),
    )
    result = score_pair(inputs, weights=ALERT_WEIGHTS)

    semantic_component = (
        semantic_similarity(cosine) if cosine is not None else 0.0
    )
    skill_component = result.components.get("skill", 0.0) if candidate_requirements else 0.0
    title_score = float(fuzz.token_set_ratio(seed.job.title, candidate.title))

    strong = (
        semantic_component >= SEMANTIC_GATE
        or skill_component >= SKILL_GATE
        or same_family
        or title_score >= TITLE_GATE
    )
    if not strong:
        return None

    final = round(
        result.final * (1.0 - title_weight) + title_score * title_weight,
        1,
    )

    matched = list(result.skill_detail.matched)
    reason_bits = [
        f"Similar to your saved job \"{seed.job.title}\" ({final:.0f}% match)"
    ]
    if matched:
        reason_bits.append("Shared skills: " + ", ".join(matched[:4]))
    elif same_family:
        reason_bits.append(f"Same job family: {seed.family}")
    elif title_score >= TITLE_GATE:
        reason_bits.append("Very similar job title")

    return final, "; ".join(reason_bits), matched


# ---------------------------------------------------------------------------
# Query + scan
# ---------------------------------------------------------------------------

def _saved_jobs(db: Session, user_id: UUID, limit: int) -> list[Job]:
    stmt = (
        select(Job)
        .join(Application, Application.job_id == Job.id)
        .where(
            Application.user_id == user_id,
            Application.status == ApplicationStatus.SAVED,
            Job.status == JobStatus.PUBLISHED,
        )
        .options(
            selectinload(Job.company),
            selectinload(Job.skills).selectinload(JobSkill.skill),
            selectinload(Job.family),
        )
        .order_by(Application.applied_at.desc(), Job.id)
        .limit(limit)
    )
    return list(db.scalars(stmt).all())


def _candidate_jobs(
    db: Session,
    user_id: UUID,
    seed_ids: list[UUID],
    since: datetime | None,
    limit: int,
) -> list[Job]:
    excluded_apps = select(Application.job_id).where(Application.user_id == user_id)
    already_alerted = select(JobAlertItem.job_id).where(JobAlertItem.user_id == user_id)

    stmt = (
        select(Job)
        .where(
            Job.status == JobStatus.PUBLISHED,
            Job.id.notin_(excluded_apps),
            Job.id.notin_(already_alerted),
        )
        .options(
            selectinload(Job.company),
            selectinload(Job.skills).selectinload(JobSkill.skill),
            selectinload(Job.family),
        )
        .order_by(Job.created_at.desc(), Job.id)
        .limit(limit)
    )
    if seed_ids:
        stmt = stmt.where(Job.id.notin_(seed_ids))
    if since is not None:
        stmt = stmt.where(Job.created_at >= since)
    return list(db.scalars(stmt).all())


def find_matches(
    db: Session,
    alert: JobAlert,
    *,
    since: datetime | None = None,
    limit: int | None = None,
    min_score: float | None = None,
) -> AlertScanResult:
    """Find newly published jobs similar to the user's saved jobs."""
    settings = get_settings()
    seeds = _saved_jobs(db, alert.user_id, settings.alert_max_seed_jobs)
    if not seeds:
        return AlertScanResult(items=[], seeds_used=0, candidates_scanned=0)

    candidate_limit = limit or max(1, int(alert.max_items))
    score_floor = float(alert.min_score if min_score is None else min_score)
    candidates = _candidate_jobs(
        db,
        alert.user_id,
        [seed.id for seed in seeds],
        since,
        settings.alert_max_new_jobs,
    )
    if not candidates:
        return AlertScanResult(items=[], seeds_used=len(seeds), candidates_scanned=0)

    title_weight = max(0.0, min(0.5, float(settings.alert_title_weight)))
    contexts = [_seed_context(seed) for seed in seeds]

    best_by_candidate: dict[UUID, AlertMatch] = {}
    for candidate in candidates:
        requirements = _job_requirements(candidate)
        best: AlertMatch | None = None
        for seed in contexts:
            scored = _similarity_against_seed(
                seed, candidate, requirements, title_weight
            )
            if scored is None:
                continue
            final, reason, matched = scored
            if final < score_floor:
                continue
            if best is None or final > best.score:
                best = AlertMatch(
                    job=candidate,
                    seed_job=seed.job,
                    score=final,
                    reason=reason,
                    matched_skills=matched,
                )
        if best is not None:
            best_by_candidate[candidate.id] = best

    ordered = sorted(
        best_by_candidate.values(),
        key=lambda match: (-match.score, str(match.job.id)),
    )
    return AlertScanResult(
        items=ordered[:candidate_limit],
        seeds_used=len(seeds),
        candidates_scanned=len(candidates),
    )


# ---------------------------------------------------------------------------
# Settings + digest creation
# ---------------------------------------------------------------------------

def get_or_create_alert(db: Session, user_id: UUID, profile_id: UUID) -> JobAlert:
    """Return the user's alert settings, creating defaults on first use."""
    alert = db.scalar(select(JobAlert).where(JobAlert.user_id == user_id))
    if alert is None:
        settings = get_settings()
        alert = JobAlert(
            user_id=user_id,
            profile_id=profile_id,
            enabled=True,
            email_enabled=True,
            digest_frequency="daily",
            min_score=settings.alert_default_min_score,
            max_items=settings.alert_default_max_items,
        )
        db.add(alert)
        db.flush()
    elif alert.profile_id != profile_id:
        alert.profile_id = profile_id
    return alert


def _cadence_seconds(alert: JobAlert) -> int | None:
    frequency = (alert.digest_frequency or "daily").lower()
    if frequency == "off":
        return None
    if frequency == "weekly":
        return _WEEKLY_SECONDS
    return _DAILY_SECONDS


def _is_due(alert: JobAlert, now: datetime, force: bool) -> bool:
    # A user who turned alerts off (or set frequency=off) stays off even when
    # the worker is run with --force; --force only skips the cadence wait.
    if not alert.enabled:
        return False
    cadence = _cadence_seconds(alert)
    if cadence is None:
        return False
    if force:
        return True
    if alert.last_digest_at is None:
        return True
    last = alert.last_digest_at
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return (now - last).total_seconds() >= cadence


def _create_digest(
    db: Session,
    alert: JobAlert,
    matches: list[AlertMatch],
    *,
    now: datetime,
    window_start: datetime,
    wants_email: bool,
) -> JobAlertDigest:
    digest = JobAlertDigest(
        alert_id=alert.id,
        user_id=alert.user_id,
        status="sent",
        item_count=len(matches),
        channel="both" if wants_email else "in_app",
        email_status="not_sent",
        window_start=window_start,
        window_end=now,
        sent_at=now,
    )
    db.add(digest)
    db.flush()

    for match in matches:
        db.add(
            JobAlertItem(
                digest_id=digest.id,
                alert_id=alert.id,
                user_id=alert.user_id,
                job_id=match.job.id,
                seed_job_id=match.seed_job.id,
                score=match.score,
                reason=match.reason,
            )
        )
        title = f"New match for your saved job: {match.job.title}"[:200]
        db.add(
            Notification(
                user_id=alert.user_id,
                digest_id=digest.id,
                type="job_alert",
                title=title,
                body=match.reason,
                link=f"/jobs/{match.job.id}",
                data={
                    "job_id": str(match.job.id),
                    "seed_job_id": str(match.seed_job.id),
                    "score": match.score,
                },
            )
        )

    alert.last_digest_at = now
    return digest


# ---------------------------------------------------------------------------
# Email rendering
# ---------------------------------------------------------------------------

def render_digest_email(
    matches: list[AlertMatch],
    base_url: str,
) -> tuple[str, str, str]:
    base = base_url.rstrip("/")
    count = len(matches)
    noun = "job" if count == 1 else "jobs"
    subject = f"{count} new {noun} matching your saved jobs"

    text_lines = [
        f"We found {count} new {noun} similar to jobs you saved on JobRec.",
        "",
    ]
    html_rows: list[str] = []
    for match in matches:
        url = f"{base}/jobs/{match.job.id}"
        company = match.job.company.name if match.job.company is not None else "Company"
        text_lines.append(f"- {match.job.title} at {company} ({match.score:.0f}% match)")
        text_lines.append(f"  {match.reason}")
        text_lines.append(f"  {url}")
        text_lines.append("")
        html_rows.append(
            "<li style=\"margin-bottom:18px\">"
            f"<a href=\"{html.escape(url)}\" style=\"font-weight:600;color:#0f766e\">"
            f"{html.escape(match.job.title)}</a>"
            f" <span style=\"color:#52525b\">at {html.escape(company)}</span>"
            f"<div style=\"margin-top:4px;color:#3f3f46\">{html.escape(match.reason)}</div>"
            "</li>"
        )
    text_lines.extend(
        [
            "Manage or turn off these alerts:",
            f"{base}/settings",
        ]
    )
    html_body = (
        "<div style=\"font-family:Arial,sans-serif;max-width:640px;margin:0 auto;color:#18181b\">"
        f"<h2 style=\"color:#0f766e\">New matches for your saved jobs</h2>"
        f"<p>We found {count} new {noun} similar to jobs you saved on JobRec.</p>"
        f"<ul style=\"padding-left:18px\">{''.join(html_rows)}</ul>"
        f"<p style=\"font-size:12px;color:#71717a\">Manage or turn off these alerts in "
        f"<a href=\"{html.escape(base)}/settings\" style=\"color:#0f766e\">Settings</a>.</p>"
        "</div>"
    )
    return subject, "\n".join(text_lines), html_body


# ---------------------------------------------------------------------------
# Worker orchestration
# ---------------------------------------------------------------------------

def _aware(moment: datetime | None) -> datetime | None:
    if moment is None:
        return None
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment


def run_alert_cycle(
    db: Session,
    *,
    now: datetime | None = None,
    dry_run: bool = False,
    force: bool = False,
    email_enabled: bool | None = None,
    user_id: UUID | None = None,
) -> dict:
    """Scan saved-job alerts and deliver digests.

    ``dry_run`` never writes alerts, digests, items, or notifications.  It is
    used by ``scripts/send_job_alerts.py --dry-run`` and the preview endpoint
    to show what *would* be sent.
    """
    settings = get_settings()
    now = _aware(now) or datetime.now(timezone.utc)
    if not settings.alerts_enabled:
        return {
            "enabled": False,
            "dry_run": dry_run,
            "users_scanned": 0,
            "digests_sent": 0,
            "items_sent": 0,
            "emails_sent": 0,
            "emails_failed": 0,
            "results": [],
        }

    stmt = (
        select(User.id, User.email, Profile.id)
        .join(Profile, Profile.user_id == User.id)
        .join(Application, Application.user_id == User.id)
        .where(
            Application.status == ApplicationStatus.SAVED,
            User.is_active.is_(True),
        )
        .distinct()
    )
    if user_id is not None:
        stmt = stmt.where(User.id == user_id)
    rows = db.execute(stmt).all()

    if email_enabled is None:
        email_enabled = settings.email_alerts_enabled

    results: list[dict] = []
    digests_sent = 0
    items_sent = 0
    emails_sent = 0
    emails_failed = 0

    for uid, email, profile_id in rows:
        alert: JobAlert | None = db.scalar(
            select(JobAlert).where(JobAlert.user_id == uid)
        )
        if alert is None:
            alert = JobAlert(
                user_id=uid,
                profile_id=profile_id,
                enabled=True,
                email_enabled=True,
                digest_frequency="daily",
                min_score=settings.alert_default_min_score,
                max_items=settings.alert_default_max_items,
            )
            if not dry_run:
                db.add(alert)
                db.flush()
        elif alert.profile_id != profile_id:
            alert.profile_id = profile_id

        if not dry_run and not _is_due(alert, now, force):
            results.append(
                {
                    "user_id": str(uid),
                    "status": "skipped",
                    "reason": "disabled_or_not_due",
                    "items": 0,
                }
            )
            continue

        window_start = _aware(alert.last_digest_at) or (
            now - timedelta(hours=settings.alert_first_run_lookback_hours)
        )
        scan = find_matches(db, alert, since=window_start)

        if dry_run:
            results.append(
                {
                    "user_id": str(uid),
                    "status": "preview",
                    "seeds_used": scan.seeds_used,
                    "candidates_scanned": scan.candidates_scanned,
                    "items": [
                        {
                            "job_id": str(match.job.id),
                            "title": match.job.title,
                            "score": match.score,
                            "seed_job_id": str(match.seed_job.id),
                            "reason": match.reason,
                        }
                        for match in scan.items
                    ],
                }
            )
            continue

        if not scan.items:
            alert.last_digest_at = now
            results.append(
                {
                    "user_id": str(uid),
                    "status": "empty",
                    "seeds_used": scan.seeds_used,
                    "candidates_scanned": scan.candidates_scanned,
                    "items": 0,
                }
            )
            continue

        wants_email = bool(email_enabled and alert.email_enabled)
        digest = _create_digest(
            db,
            alert,
            scan.items,
            now=now,
            window_start=window_start,
            wants_email=wants_email,
        )
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            log.warning("alert digest race for user %s; skipping", uid)
            results.append(
                {
                    "user_id": str(uid),
                    "status": "skipped",
                    "reason": "duplicate",
                    "items": 0,
                }
            )
            continue

        digests_sent += 1
        items_sent += len(scan.items)

        email_status = "disabled" if not wants_email else "not_sent"
        email_error: str | None = None
        if wants_email:
            subject, text_body, html_body = render_digest_email(
                scan.items, settings.frontend_public_url
            )
            email_status, email_error = send_email(
                email, subject, text_body, html_body
            )
            digest_row = db.get(JobAlertDigest, digest.id)
            if digest_row is not None:
                digest_row.email_status = email_status
                digest_row.error = email_error
                # In-app notifications were always written; only mark the
                # digest as dual-channel when the email actually went out.
                digest_row.channel = "both" if email_status == "sent" else "in_app"
                if email_status == "failed":
                    digest_row.status = "failed"
                db.commit()
            if email_status == "sent":
                emails_sent += 1
            elif email_status == "failed":
                emails_failed += 1

        results.append(
            {
                "user_id": str(uid),
                "status": "sent",
                "seeds_used": scan.seeds_used,
                "candidates_scanned": scan.candidates_scanned,
                "items": len(scan.items),
                "email_status": email_status,
                "titles": [match.job.title for match in scan.items],
            }
        )

    if not dry_run:
        db.commit()

    return {
        "enabled": True,
        "dry_run": dry_run,
        "generated_at": now.isoformat(),
        "users_scanned": len(rows),
        "digests_sent": digests_sent,
        "items_sent": items_sent,
        "emails_sent": emails_sent,
        "emails_failed": emails_failed,
        "results": results,
    }
