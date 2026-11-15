"""Tests for Phase 1: Core Data Integrity, Profile Data, and Embedding Safety.

Uses the active PostgreSQL test database to verify:
1. Application ownership integrity & composite FK
2. Profile source-of-truth & idempotent backfill
3. Embedding provenance tracking & vector space separation
4. Skill alias normalization & graph check constraints
"""

import hashlib
import uuid
import numpy as np
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.db import SessionLocal
from app.models.application import Application
from app.models.company import Company
from app.models.enums import SkillEdgeType, UserRole
from app.models.job import Job
from app.models.profile import Profile
from app.models.profile_entities import Education, Experience
from app.models.skill import Skill
from app.models.skill_graph import SkillAlias, SkillEdge
from app.models.user import User
from app.services.embeddings import (
    ensure_job_embeddings,
    ensure_profile_embedding,
    is_compatible_embedding,
)
from app.services.profile_sync import sync_jsonb_to_structured
from app.services.recommender import _ProfileContext
from app.services.scoring import score_pair


class FakeEmbedder:
    """Deterministic fake embedder producing normalized 384-d vectors without network."""

    def __init__(self, backend="fake_minilm", model_name="fake-model", dimension=384):
        self.backend = backend
        self.model_name = model_name
        self.version = "v1"
        self.dimension = dimension

    def encode(self, texts: list[str]) -> np.ndarray:
        vecs = []
        for t in texts:
            seed = int(hashlib.md5(t.encode("utf-8")).hexdigest()[:8], 16)
            rng = np.random.RandomState(seed)
            v = rng.randn(self.dimension).astype(np.float32)
            norm = np.linalg.norm(v)
            vecs.append(v / norm if norm > 0 else v)
        return np.asarray(vecs, dtype=np.float32)

    def encode_one(self, text: str) -> list[float]:
        return self.encode([text])[0].tolist()


# ---------------------------------------------------------------------------
# 1. Application Ownership Integrity Tests (Phase 1.1)
# ---------------------------------------------------------------------------

def test_application_valid_same_owner():
    """Verify that an application with matching user_id and profile.user_id succeeds."""
    with SessionLocal() as db:
        user = User(
            email=f"valid_applicant_{uuid.uuid4().hex[:6]}@test.com",
            hashed_password="hash",
            role=UserRole.JOB_SEEKER,
        )
        db.add(user)
        db.flush()

        profile = Profile(user_id=user.id, first_name="Valid", last_name="User")
        db.add(profile)

        company = Company(
            name="Test Co",
            slug=f"test-co-{uuid.uuid4().hex[:6]}",
            created_by_user_id=user.id,
        )
        db.add(company)
        db.flush()

        job = Job(
            title="Engineer",
            description="Desc",
            location="Remote",
            company_id=company.id,
            posted_by_user_id=user.id,
            source="test",
        )
        db.add(job)
        db.flush()

        try:
            # Same owner application
            app = Application(
                job_id=job.id,
                user_id=user.id,
                profile_id=profile.id,
            )
            db.add(app)
            db.commit()

            # Verify persisted
            saved = db.get(Application, app.id)
            assert saved is not None
            assert saved.user_id == user.id
            assert saved.profile_id == profile.id
        finally:
            # Cleanup so test doesn't pollute native recommendation corpus
            db.rollback()
            for obj in [app, job, company, profile, user]:
                try:
                    db.delete(obj)
                    db.commit()
                except Exception:
                    db.rollback()


def test_application_cross_owner_rejected_by_db():
    """Verify that assigning User A's application to User B's profile violates the composite FK."""
    with SessionLocal() as db:
        user_a = User(email=f"user_a_{uuid.uuid4().hex[:6]}@test.com", hashed_password="h", role=UserRole.JOB_SEEKER)
        user_b = User(email=f"user_b_{uuid.uuid4().hex[:6]}@test.com", hashed_password="h", role=UserRole.JOB_SEEKER)
        db.add_all([user_a, user_b])
        db.flush()

        profile_a = Profile(user_id=user_a.id, first_name="A", last_name="User")
        profile_b = Profile(user_id=user_b.id, first_name="B", last_name="User")
        company = Company(name="Co", slug=f"co-{uuid.uuid4().hex[:6]}", created_by_user_id=user_a.id)
        db.add_all([profile_a, profile_b, company])
        db.flush()

        job = Job(title="Dev", description="Desc", location="Remote", company_id=company.id, posted_by_user_id=user_a.id)
        db.add(job)
        db.flush()

        # User A applying with User B's profile
        invalid_app = Application(
            job_id=job.id,
            user_id=user_a.id,
            profile_id=profile_b.id,  # MISMATCH!
        )
        db.add(invalid_app)

        with pytest.raises(IntegrityError) as exc_info:
            db.commit()

        assert "fk_applications_profile_user" in str(exc_info.value)
        db.rollback()


# ---------------------------------------------------------------------------
# 2. Profile Source-of-Truth & Backfill Tests (Phase 1.2)
# ---------------------------------------------------------------------------

def test_sync_jsonb_to_structured_idempotent():
    """Verify that JSONB education and experience backfill to structured rows without duplicates."""
    with SessionLocal() as db:
        user = User(email=f"sync_user_{uuid.uuid4().hex[:6]}@test.com", hashed_password="h")
        db.add(user)
        db.flush()

        profile = Profile(
            user_id=user.id,
            first_name="Sync",
            last_name="Test",
            education=[
                {"degree": "B.Tech Computer Science", "institution": "IIT Bombay", "grad_year": 2022, "is_primary": True},
                {"degree": "M.S. Data Science", "institution": "Stanford", "grad_year": 2024},
            ],
            work_experience=[
                {"title": "Software Engineer", "company": "Google", "start_date": "2022-07", "end_date": "2024-06"},
                {"title": "Senior Engineer", "company": "Stripe", "start_date": "2024-07", "current": True},
            ],
        )
        db.add(profile)
        db.commit()

        # Run 1: initial backfill
        stats1 = sync_jsonb_to_structured(db, profile)
        db.commit()

        assert stats1["education_added"] == 2
        assert stats1["experience_added"] == 2

        edu_rows = db.scalars(select(Education).where(Education.profile_id == profile.id)).all()
        exp_rows = db.scalars(select(Experience).where(Experience.profile_id == profile.id)).all()
        assert len(edu_rows) == 2
        assert len(exp_rows) == 2

        # Run 2: idempotent re-run must add 0 duplicates
        stats2 = sync_jsonb_to_structured(db, profile)
        db.commit()

        assert stats2["education_added"] == 0
        assert stats2["experience_added"] == 0

        edu_rows_after = db.scalars(select(Education).where(Education.profile_id == profile.id)).all()
        exp_rows_after = db.scalars(select(Experience).where(Experience.profile_id == profile.id)).all()
        assert len(edu_rows_after) == 2
        assert len(exp_rows_after) == 2

        # Verify structured updates are preserved
        assert any(e.degree == "B.Tech Computer Science" for e in edu_rows_after)
        assert any(e.company == "Google" for e in exp_rows_after)


# ---------------------------------------------------------------------------
# 3. Embedding Provenance & Separation Tests (Phase 1.3)
# ---------------------------------------------------------------------------

def test_embedding_provenance_and_separation():
    """Verify that embeddings carry full provenance and incompatible spaces are never compared."""
    with SessionLocal() as db:
        user = User(email=f"emb_user_{uuid.uuid4().hex[:6]}@test.com", hashed_password="h")
        db.add(user)
        db.flush()

        profile = Profile(user_id=user.id, first_name="Emb", last_name="User", headline="ML Engineer")
        company = Company(name="AI Corp", slug=f"ai-{uuid.uuid4().hex[:6]}", created_by_user_id=user.id)
        db.add_all([profile, company])
        db.flush()

        job1 = Job(title="ML Engineer", description="PyTorch", location="Remote", company_id=company.id, posted_by_user_id=user.id)
        job2 = Job(title="ML Engineer", description="PyTorch", location="Remote", company_id=company.id, posted_by_user_id=user.id)
        db.add_all([job1, job2])
        db.flush()

        embedder_a = FakeEmbedder(backend="minilm", model_name="all-MiniLM-L6-v2")
        embedder_b = FakeEmbedder(backend="hashing", model_name="sklearn-hash")

        # Profile gets MiniLM embedding
        ensure_profile_embedding(profile, embedder=embedder_a)
        assert profile.embedding_backend == "minilm"
        assert profile.embedding_model == "all-MiniLM-L6-v2"
        assert profile.embedding_dimension == 384
        assert profile.embedding_content_hash is not None

        # Job 1 gets MiniLM embedding
        ensure_job_embeddings([job1], embedder=embedder_a)
        assert job1.embedding_backend == "minilm"

        # Job 2 gets Hashing embedding
        ensure_job_embeddings([job2], embedder=embedder_b)
        assert job2.embedding_backend == "hashing"

        # Compatibility check
        assert is_compatible_embedding(profile, job1) is True
        assert is_compatible_embedding(profile, job2) is False

        # Scoring check via profile context
        ctx = _ProfileContext(profile)

        # Compatible job: cosine is calculated
        inputs1 = ctx.inputs_for(job1)
        assert inputs1.semantic_cosine is not None

        # Incompatible job: semantic_cosine is None -> falls back to neutral prior (70.0)
        inputs2 = ctx.inputs_for(job2)
        assert inputs2.semantic_cosine is None

        scores2 = score_pair(inputs2)
        assert scores2.components["semantic"] == 70.0  # Safe neutral fallback!


# ---------------------------------------------------------------------------
# 4. Skill Alias Normalization & Graph Constraints (Phase 1.4)
# ---------------------------------------------------------------------------

def test_skill_alias_case_and_whitespace_uniqueness():
    """Verify that skill aliases with different casing or whitespace are rejected as duplicates."""
    with SessionLocal() as db:
        skill = Skill(name=f"Skill_{uuid.uuid4().hex[:6]}")
        db.add(skill)
        db.flush()

        unique_alias = f"CustomAlias_{uuid.uuid4().hex[:6]}"
        alias1 = SkillAlias(alias=unique_alias, skill_id=skill.id)
        db.add(alias1)
        db.commit()

        assert alias1.normalized_alias == unique_alias.lower()

        # Attempt to insert whitespace & lower variant
        alias2 = SkillAlias(alias=f"  {unique_alias.lower()}  ", skill_id=skill.id)
        db.add(alias2)

        with pytest.raises(IntegrityError) as exc_info:
            db.commit()

        assert "uq_skill_aliases_normalized_alias" in str(exc_info.value)
        db.rollback()


def test_skill_edge_self_loop_rejected():
    """Verify that a skill edge pointing from a skill to itself is rejected by CHECK constraint."""
    with SessionLocal() as db:
        skill = Skill(name=f"SelfLoop_{uuid.uuid4().hex[:6]}")
        db.add(skill)
        db.flush()

        edge = SkillEdge(
            from_skill_id=skill.id,
            to_skill_id=skill.id,  # Self loop!
            edge_type=SkillEdgeType.PREREQ,
            weight=1.0,
        )
        db.add(edge)

        with pytest.raises(IntegrityError) as exc_info:
            db.commit()

        assert "ck_skill_edges_no_self_loop" in str(exc_info.value)
        db.rollback()


def test_skill_edge_weight_range_rejected():
    """Verify that invalid edge weights (< 0 or > 10) are rejected by CHECK constraint."""
    with SessionLocal() as db:
        s1 = Skill(name=f"S1_{uuid.uuid4().hex[:6]}")
        s2 = Skill(name=f"S2_{uuid.uuid4().hex[:6]}")
        db.add_all([s1, s2])
        db.flush()

        # Negative weight
        invalid_edge = SkillEdge(
            from_skill_id=s1.id,
            to_skill_id=s2.id,
            edge_type=SkillEdgeType.TRANSFER,
            weight=-0.5,
        )
        db.add(invalid_edge)

        with pytest.raises(IntegrityError) as exc_info:
            db.commit()

        assert "ck_skill_edges_weight_range" in str(exc_info.value)
        db.rollback()
