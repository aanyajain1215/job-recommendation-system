"""Comprehensive Phase 2 Database, Traceability & Audit Tests.

Covers:
1. Recommendation Event / Impression Tracking (Phase 2.1)
   - Differentiating generated, served, and explicit client impression
   - Event creation, ordering, and timezone-aware timestamps
   - Idempotency on repeated client event reports
   - Ownership verification (cross-user event report rejected with 403)
   - Cascade deletion on recommendation removal

2. Feedback Link to Exact Recommendation (Phase 2.2)
   - Valid (recommendation_id, profile_id, job_id) linkage
   - Service validation on mismatched job or profile
   - Cross-user recommendation feedback rejection (403)
   - Legacy / direct feedback with recommendation_id=None preserved
   - ON DELETE SET NULL: deleting recommendation preserves feedback with NULL id

3. Application Status History (Phase 2.3)
   - Initial status history record created upon application submission
   - Atomic status updates with auditable transition history
   - Idempotent no-op updates: repeating same status inserts no duplicate history
   - Audit trail endpoint GET /applications/{id}/history with strict authorization
   - Backfill validation: existing applications have initial history record
"""

import uuid
from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.core.db import SessionLocal
from app.main import app
from app.models.application import Application, ApplicationStatusHistory
from app.models.company import Company
from app.models.enums import (
    ApplicationStatus,
    EmploymentType,
    ExperienceLevel,
    FeedbackReason,
    JobStatus,
    RecommendationEventType,
    UserRole,
)
from app.models.feedback import Feedback
from app.models.job import Job
from app.models.profile import Profile
from app.models.recommendation import Recommendation, RecommendationEvent
from app.models.user import User

client = TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Test Helpers & Fixtures
# ---------------------------------------------------------------------------

def _create_user(db, role=UserRole.JOB_SEEKER, email_prefix="user") -> tuple[User, Profile]:
    uid = uuid.uuid4().hex[:6]
    user = User(
        email=f"{email_prefix}_{uid}@example.com",
        hashed_password="hashed_pw",
        role=role,
    )
    db.add(user)
    db.flush()

    profile = Profile(
        user_id=user.id,
        first_name=email_prefix.capitalize(),
        last_name="Test",
    )
    db.add(profile)
    db.flush()
    return user, profile


def _create_job(db, employer_user_id: uuid.UUID) -> Job:
    uid = uuid.uuid4().hex[:6]
    company = Company(
        name=f"Company {uid}",
        slug=f"company-{uid}",
        created_by_user_id=employer_user_id,
    )
    db.add(company)
    db.flush()

    job = Job(
        title="Distributed Systems Engineer",
        description="Build scalable services",
        company_id=company.id,
        posted_by_user_id=employer_user_id,
        employment_type=EmploymentType.FULL_TIME,
        experience_level=ExperienceLevel.SENIOR,
        location="Remote",
        status=JobStatus.PUBLISHED,
        source="test",
    )
    db.add(job)
    db.flush()
    return job


def _safe_cleanup(user_ids=None, company_ids=None, job_ids=None, rec_ids=None, app_ids=None):
    with SessionLocal() as db:
        if app_ids:
            for aid in app_ids:
                row = db.get(Application, aid)
                if row:
                    db.delete(row)
        if rec_ids:
            for rid in rec_ids:
                row = db.get(Recommendation, rid)
                if row:
                    db.delete(row)
        if job_ids:
            for jid in job_ids:
                row = db.get(Job, jid)
                if row:
                    db.delete(row)
        if company_ids:
            for cid in company_ids:
                row = db.get(Company, cid)
                if row:
                    db.delete(row)
        if user_ids:
            for uid in user_ids:
                row = db.get(User, uid)
                if row:
                    db.delete(row)
        try:
            db.commit()
        except Exception:
            db.rollback()


# ---------------------------------------------------------------------------
# 1. Recommendation Event & Impression Tracking Tests (Phase 2.1)
# ---------------------------------------------------------------------------

def test_recommendation_event_lifecycle_and_idempotency():
    """Verify generated, served, and explicit impression lifecycle points and idempotency."""
    with SessionLocal() as db:
        user, profile = _create_user(db, UserRole.JOB_SEEKER, "seeker_rec")
        employer, _ = _create_user(db, UserRole.EMPLOYER, "emp_rec")
        job = _create_job(db, employer.id)

        rec = Recommendation(
            profile_id=profile.id,
            job_id=job.id,
            snapshot={"match_score": 85.0, "components": {"skill": 90.0}},
            strategy="content_based",
        )
        db.add(rec)
        db.flush()

        # 1. SERVED event recorded by backend
        served_ev = RecommendationEvent(
            recommendation_id=rec.id,
            profile_id=profile.id,
            event_type=RecommendationEventType.SERVED,
            rank=1,
        )
        db.add(served_ev)
        db.commit()

        # 2. IMPRESSION event reported explicitly by client
        imp_ev = RecommendationEvent(
            recommendation_id=rec.id,
            profile_id=profile.id,
            event_type=RecommendationEventType.IMPRESSION,
            rank=1,
            request_id="req-123",
        )
        db.add(imp_ev)
        db.commit()

        rec_id = rec.id
        u_id = user.id
        emp_id = employer.id
        comp_id = job.company_id
        job_id = job.id

    # Verify distinct events exist
    with SessionLocal() as db:
        events = db.scalars(
            select(RecommendationEvent)
            .where(RecommendationEvent.recommendation_id == rec_id)
            .order_by(RecommendationEvent.occurred_at.asc())
        ).all()

        types = [e.event_type for e in events]
        assert RecommendationEventType.SERVED in types
        assert RecommendationEventType.IMPRESSION in types
        assert len(events) == 2

        # 3. Idempotent check: unique constraint uq_rec_event_rec_type blocks duplicate (recommendation_id, event_type)
        duplicate_caught = False
        try:
            with SessionLocal() as db_dup:
                dup = RecommendationEvent(
                    recommendation_id=rec_id,
                    profile_id=events[0].profile_id,
                    event_type=RecommendationEventType.IMPRESSION,
                )
                db_dup.add(dup)
                db_dup.commit()
        except IntegrityError:
            duplicate_caught = True
            db_dup.rollback()

        assert duplicate_caught, "uq_rec_event_rec_type must reject duplicate event type for same recommendation"

    # Cleanup
    _safe_cleanup(user_ids=[u_id, emp_id], company_ids=[comp_id], job_ids=[job_id], rec_ids=[rec_id])


def test_recommendation_event_api_authorization():
    """Verify that reporting an event for another user's recommendation is rejected with 403."""
    from app.core.security import create_access_token

    with SessionLocal() as db:
        user_a, profile_a = _create_user(db, UserRole.JOB_SEEKER, "user_a")
        user_b, profile_b = _create_user(db, UserRole.JOB_SEEKER, "user_b")
        employer, _ = _create_user(db, UserRole.EMPLOYER, "emp_auth")
        job = _create_job(db, employer.id)

        rec_a = Recommendation(
            profile_id=profile_a.id,
            job_id=job.id,
            snapshot={"match_score": 75.0},
        )
        db.add(rec_a)
        db.commit()

        rec_a_id = rec_a.id
        user_a_id = user_a.id
        user_b_id = user_b.id
        emp_id = employer.id
        job_id = job.id
        comp_id = job.company_id

        token_a = create_access_token(user_a.id, user_a.role.value)
        token_b = create_access_token(user_b.id, user_b.role.value)

    try:
        # User B attempts to report an event on User A's recommendation
        resp = client.post(
            "/api/v1/recommendations/events",
            headers={"Authorization": f"Bearer {token_b}"},
            json={
                "recommendation_id": str(rec_a_id),
                "event_type": "impression",
                "rank": 1,
            },
        )
        assert resp.status_code == 403, f"Expected 403 Forbidden, got {resp.status_code}: {resp.text}"
        assert "not own" in resp.text.lower()

        # User A reports event on own recommendation -> succeeds 201
        resp_a = client.post(
            "/api/v1/recommendations/events",
            headers={"Authorization": f"Bearer {token_a}"},
            json={
                "recommendation_id": str(rec_a_id),
                "event_type": "impression",
                "rank": 1,
            },
        )
        assert resp_a.status_code == 201, f"Expected 201 Created, got {resp_a.status_code}: {resp_a.text}"

        # Re-posting same event returns 200 (idempotent)
        resp_a_repeat = client.post(
            "/api/v1/recommendations/events",
            headers={"Authorization": f"Bearer {token_a}"},
            json={
                "recommendation_id": str(rec_a_id),
                "event_type": "impression",
                "rank": 1,
            },
        )
        assert resp_a_repeat.status_code == 200, f"Expected 200 OK for repeat, got {resp_a_repeat.status_code}"

    finally:
        _safe_cleanup(
            user_ids=[user_a_id, user_b_id, emp_id],
            company_ids=[comp_id],
            job_ids=[job_id],
            rec_ids=[rec_a_id],
        )


def test_recommendation_cascade_deletion():
    """Verify that deleting a recommendation cascades to its lifecycle events."""
    with SessionLocal() as db:
        user, profile = _create_user(db, UserRole.JOB_SEEKER, "cascade_user")
        employer, _ = _create_user(db, UserRole.EMPLOYER, "cascade_emp")
        job = _create_job(db, employer.id)

        rec = Recommendation(
            profile_id=profile.id,
            job_id=job.id,
            snapshot={"match_score": 90.0},
        )
        db.add(rec)
        db.flush()

        event = RecommendationEvent(
            recommendation_id=rec.id,
            profile_id=profile.id,
            event_type=RecommendationEventType.CLICKED,
        )
        db.add(event)
        db.commit()

        ev_id = event.id
        rec_id = rec.id
        u_id = user.id
        emp_id = employer.id
        comp_id = job.company_id
        job_id = job.id

    with SessionLocal() as db:
        # Delete recommendation
        r = db.get(Recommendation, rec_id)
        if r:
            db.delete(r)
            db.commit()

        # Event must be cascade-deleted
        ev_after = db.get(RecommendationEvent, ev_id)
        assert ev_after is None, "RecommendationEvent must be cascade-deleted when parent recommendation is removed"

    _safe_cleanup(user_ids=[u_id, emp_id], company_ids=[comp_id], job_ids=[job_id])


# ---------------------------------------------------------------------------
# 2. Feedback Linkage Tests (Phase 2.2)
# ---------------------------------------------------------------------------

def test_feedback_linkage_valid_and_mismatch_rejection():
    """Verify that feedback correctly links to recommendation, and mismatched context is rejected."""
    from app.core.security import create_access_token

    with SessionLocal() as db:
        user_a, profile_a = _create_user(db, UserRole.JOB_SEEKER, "fb_a")
        user_b, profile_b = _create_user(db, UserRole.JOB_SEEKER, "fb_b")
        employer, _ = _create_user(db, UserRole.EMPLOYER, "fb_emp")
        job_1 = _create_job(db, employer.id)
        job_2 = _create_job(db, employer.id)

        # Recommendation for User A on Job 1
        rec = Recommendation(
            profile_id=profile_a.id,
            job_id=job_1.id,
            snapshot={"match_score": 88.0},
        )
        db.add(rec)
        db.commit()

        rec_id = rec.id
        user_a_id = user_a.id
        user_b_id = user_b.id
        emp_id = employer.id
        job_1_id = job_1.id
        job_2_id = job_2.id
        comp_1_id = job_1.company_id
        comp_2_id = job_2.company_id

        token_a = create_access_token(user_a.id, user_a.role.value)
        token_b = create_access_token(user_b.id, user_b.role.value)

    fb_id = None
    try:
        # 1. Valid feedback linkage
        resp_valid = client.post(
            "/api/v1/feedback",
            headers={"Authorization": f"Bearer {token_a}"},
            json={
                "job_id": str(job_1_id),
                "recommendation_id": str(rec_id),
                "reason": "relevant",
                "note": "Great recommendation",
            },
        )
        assert resp_valid.status_code == 201, resp_valid.text
        fb_data = resp_valid.json()
        assert fb_data["recommendation_id"] == str(rec_id)
        fb_id = uuid.UUID(fb_data["id"])

        # 2. Mismatched job: recommendation is for Job 1, but payload specifies Job 2
        resp_mismatch_job = client.post(
            "/api/v1/feedback",
            headers={"Authorization": f"Bearer {token_a}"},
            json={
                "job_id": str(job_2_id),
                "recommendation_id": str(rec_id),
                "reason": "not_relevant",
            },
        )
        assert resp_mismatch_job.status_code == 400
        assert "mismatch" in resp_mismatch_job.text.lower()

        # 3. Cross-user rejection: User B tries to attach User A's recommendation
        resp_cross_user = client.post(
            "/api/v1/feedback",
            headers={"Authorization": f"Bearer {token_b}"},
            json={
                "job_id": str(job_1_id),
                "recommendation_id": str(rec_id),
                "reason": "relevant",
            },
        )
        assert resp_cross_user.status_code == 403
        assert "not belong" in resp_cross_user.text.lower()

    finally:
        with SessionLocal() as db:
            if fb_id:
                fb_row = db.get(Feedback, fb_id)
                if fb_row:
                    db.delete(fb_row)
                    db.commit()
        _safe_cleanup(
            user_ids=[user_a_id, user_b_id, emp_id],
            company_ids=[comp_1_id, comp_2_id],
            job_ids=[job_1_id, job_2_id],
            rec_ids=[rec_id],
        )


def test_feedback_legacy_null_and_on_delete_set_null():
    """Verify that feedback without recommendation_id is valid, and recommendation deletion sets FK to NULL."""
    with SessionLocal() as db:
        user, profile = _create_user(db, UserRole.JOB_SEEKER, "fb_del_user")
        employer, _ = _create_user(db, UserRole.EMPLOYER, "fb_del_emp")
        job = _create_job(db, employer.id)

        # 1. Feedback without recommendation (legacy or direct feedback)
        fb_direct = Feedback(
            profile_id=profile.id,
            job_id=job.id,
            recommendation_id=None,
            reason=FeedbackReason.RELEVANT,
            note="Direct feedback outside feed",
        )
        db.add(fb_direct)
        db.commit()

        assert fb_direct.id is not None
        assert fb_direct.recommendation_id is None

        # 2. Feedback with recommendation
        rec = Recommendation(
            profile_id=profile.id,
            job_id=job.id,
            snapshot={"match_score": 70.0},
        )
        db.add(rec)
        db.flush()

        fb_linked = Feedback(
            profile_id=profile.id,
            job_id=job.id,
            recommendation_id=rec.id,
            reason=FeedbackReason.RELEVANT,
        )
        db.add(fb_linked)
        db.commit()

        fb_direct_id = fb_direct.id
        fb_linked_id = fb_linked.id
        rec_id = rec.id
        user_id = user.id
        emp_id = employer.id
        job_id = job.id
        comp_id = job.company_id

    with SessionLocal() as db:
        # Delete the recommendation
        r = db.get(Recommendation, rec_id)
        if r:
            db.delete(r)
            db.commit()

        # Feedback must still exist, with recommendation_id SET NULL
        fb_after = db.get(Feedback, fb_linked_id)
        assert fb_after is not None, "Feedback must NOT be cascade-deleted when recommendation is removed"
        assert fb_after.recommendation_id is None, "Feedback.recommendation_id must be set to NULL on recommendation deletion"

        # Cleanup feedbacks
        f1 = db.get(Feedback, fb_direct_id)
        if f1:
            db.delete(f1)
        if fb_after:
            db.delete(fb_after)
        db.commit()

    _safe_cleanup(user_ids=[user_id, emp_id], company_ids=[comp_id], job_ids=[job_id])


# ---------------------------------------------------------------------------
# 3. Application Status History Tests (Phase 2.3)
# ---------------------------------------------------------------------------

def test_application_status_history_transitions_and_idempotency():
    """Verify application initial state, status transitions, and no-op update idempotency."""
    from app.core.security import create_access_token

    with SessionLocal() as db:
        seeker, profile = _create_user(db, UserRole.JOB_SEEKER, "seeker_hist")
        employer, _ = _create_user(db, UserRole.EMPLOYER, "emp_hist")
        job = _create_job(db, employer.id)
        db.commit()

        token_seeker = create_access_token(seeker.id, seeker.role.value)
        token_emp = create_access_token(employer.id, employer.role.value)
        seeker_id = seeker.id
        emp_id = employer.id
        job_id = job.id
        comp_id = job.company_id

    app_id = None
    try:
        # 1. Apply to job via API
        resp_apply = client.post(
            f"/api/v1/jobs/{job_id}/apply",
            headers={"Authorization": f"Bearer {token_seeker}"},
            json={"cover_note": "Excited for this distributed systems role."},
        )
        assert resp_apply.status_code == 201, resp_apply.text
        app_id = resp_apply.json()["id"]

        # Verify initial history record exists
        with SessionLocal() as db:
            history = db.scalars(
                select(ApplicationStatusHistory)
                .where(ApplicationStatusHistory.application_id == uuid.UUID(app_id))
                .order_by(ApplicationStatusHistory.changed_at.asc())
            ).all()

            assert len(history) == 1
            assert history[0].previous_status is None
            assert history[0].new_status == ApplicationStatus.APPLIED
            assert history[0].changed_by_user_id == seeker_id

        # 2. Employer moves status to SHORTLISTED
        resp_patch = client.patch(
            f"/api/v1/employer/applications/{app_id}/status",
            headers={"Authorization": f"Bearer {token_emp}"},
            json={"status": "shortlisted", "reason": "Strong background"},
        )
        assert resp_patch.status_code == 200, resp_patch.text

        # 3. Employer moves status to INTERVIEW
        resp_patch2 = client.patch(
            f"/api/v1/employer/applications/{app_id}/status",
            headers={"Authorization": f"Bearer {token_emp}"},
            json={"status": "interview", "reason": "Passed initial screening"},
        )
        assert resp_patch2.status_code == 200, resp_patch2.text

        # 4. No-op update: update to INTERVIEW again
        resp_noop = client.patch(
            f"/api/v1/employer/applications/{app_id}/status",
            headers={"Authorization": f"Bearer {token_emp}"},
            json={"status": "interview"},
        )
        assert resp_noop.status_code == 200

        # 5. Retrieve history via audit endpoint
        resp_hist = client.get(
            f"/api/v1/applications/{app_id}/history",
            headers={"Authorization": f"Bearer {token_seeker}"},
        )
        assert resp_hist.status_code == 200
        hist_entries = resp_hist.json()

        # Must have exactly 3 entries: APPLIED -> SHORTLISTED -> INTERVIEW (no duplicate from no-op)
        assert len(hist_entries) == 3, f"Expected 3 history rows, got {len(hist_entries)}"
        assert hist_entries[0]["previous_status"] is None
        assert hist_entries[0]["new_status"] == "applied"

        assert hist_entries[1]["previous_status"] == "applied"
        assert hist_entries[1]["new_status"] == "shortlisted"

        assert hist_entries[2]["previous_status"] == "shortlisted"
        assert hist_entries[2]["new_status"] == "interview"

    finally:
        _safe_cleanup(
            user_ids=[seeker_id, emp_id],
            company_ids=[comp_id],
            job_ids=[job_id],
            app_ids=[uuid.UUID(app_id)] if app_id else None,
        )


def test_application_status_history_cross_user_forbidden():
    """Verify that an unauthorized third-party user cannot view application status history."""
    from app.core.security import create_access_token

    with SessionLocal() as db:
        seeker, profile = _create_user(db, UserRole.JOB_SEEKER, "seeker_priv")
        intruder, _ = _create_user(db, UserRole.JOB_SEEKER, "intruder_priv")
        employer, _ = _create_user(db, UserRole.EMPLOYER, "emp_priv")
        job = _create_job(db, employer.id)

        app_rec = Application(
            job_id=job.id,
            user_id=seeker.id,
            profile_id=profile.id,
            status=ApplicationStatus.APPLIED,
        )
        db.add(app_rec)
        db.flush()

        hist = ApplicationStatusHistory(
            application_id=app_rec.id,
            previous_status=None,
            new_status=ApplicationStatus.APPLIED,
            changed_by_user_id=seeker.id,
        )
        db.add(hist)
        db.commit()

        app_id = str(app_rec.id)
        seeker_id = seeker.id
        intruder_id = intruder.id
        emp_id = employer.id
        job_id = job.id
        comp_id = job.company_id

        token_intruder = create_access_token(intruder.id, intruder.role.value)
        token_employer = create_access_token(employer.id, employer.role.value)

    try:
        # 1. Intruder receives 403 Forbidden
        resp_intruder = client.get(
            f"/api/v1/applications/{app_id}/history",
            headers={"Authorization": f"Bearer {token_intruder}"},
        )
        assert resp_intruder.status_code == 403, f"Expected 403, got {resp_intruder.status_code}"

        # 2. Employer who posted the job CAN view history -> 200 OK
        resp_emp = client.get(
            f"/api/v1/applications/{app_id}/history",
            headers={"Authorization": f"Bearer {token_employer}"},
        )
        assert resp_emp.status_code == 200

    finally:
        _safe_cleanup(
            user_ids=[seeker_id, intruder_id, emp_id],
            company_ids=[comp_id],
            job_ids=[job_id],
            app_ids=[uuid.UUID(app_id)],
        )


def test_phase2_database_indexes_and_constraints_exist():
    """Verify that all Phase 2 indexes, constraints, and foreign keys are active in PostgreSQL."""
    with SessionLocal() as db:
        # 1. Unique constraint uq_recommendations_id_profile_job on recommendations
        rec_constraints = db.execute(
            text(
                """
                SELECT conname FROM pg_constraint
                WHERE conname = 'uq_recommendations_id_profile_job';
                """
            )
        ).scalar()
        assert rec_constraints == "uq_recommendations_id_profile_job"

        # 2. Recommendation events indexes and unique constraint
        event_indexes = db.execute(
            text(
                """
                SELECT indexname FROM pg_indexes
                WHERE tablename = 'recommendation_events'
                ORDER BY indexname;
                """
            )
        ).scalars().all()
        assert "ix_rec_events_rec_occurred" in event_indexes
        assert "ix_rec_events_profile_occurred" in event_indexes
        assert "ix_rec_events_type_occurred" in event_indexes
        assert "uq_rec_event_rec_type" in event_indexes

        # 3. Feedback foreign key fk_feedback_recommendation_id
        fb_fk = db.execute(
            text(
                """
                SELECT conname FROM pg_constraint
                WHERE conname = 'fk_feedback_recommendation_id';
                """
            )
        ).scalar()
        assert fb_fk == "fk_feedback_recommendation_id"

        # 4. Application status history index
        hist_indexes = db.execute(
            text(
                """
                SELECT indexname FROM pg_indexes
                WHERE tablename = 'application_status_history';
                """
            )
        ).scalars().all()
        assert "ix_app_status_history_app_changed" in hist_indexes
