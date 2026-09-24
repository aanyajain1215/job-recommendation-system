"""§17 NL search: whitelist rejection, enum/int coercion, FTS fallback, RRF.

The LLM (when present) may only emit whitelisted filter fields — unknown
fields are dropped, enums validated by Pydantic, min_salary int-coerced.
Without a provider the query degrades to plain full-text search.  Hybrid
ranking fuses FTS/KNN/skill-count orders with RRF(k=60), deterministic to
the tie-break.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.core.db import SessionLocal
from app.main import app
from app.models.enums import EmploymentType, ExperienceLevel
from app.models.job import Job
from app.services import nl_search
from app.services.llm.validators import validate_whitelisted

client = TestClient(app, raise_server_exceptions=False)


class TestWhitelistAndCoercion:

    def test_sanitize_drops_unknown_fields(self):
        raw = {"keywords": "data engineer", "salary": 999999, "exec_sql": "DROP"}
        clean = nl_search.sanitize(raw)
        assert clean == {"keywords": "data engineer"}
        problems = validate_whitelisted(raw, nl_search.ALLOWED_FIELDS)
        assert len(problems) == 2

    def test_allowed_fields_are_exactly_p7(self):
        assert set(nl_search.ALLOWED_FIELDS) == {
            "keywords", "location", "remote_only", "employment_type",
            "experience_level", "min_salary", "skills",
        }

    def test_extra_model_fields_ignored(self):
        filters = nl_search.SearchFilters(**{
            "keywords": "backend", "evil_field": "x",
        })
        dump = filters.model_dump()
        assert "evil_field" not in dump
        assert dump["keywords"] == "backend"

    def test_enum_values_validated(self):
        ok = nl_search.SearchFilters(employment_type="contract")
        assert ok.employment_type == EmploymentType.CONTRACT
        ok2 = nl_search.SearchFilters(experience_level="senior")
        assert ok2.experience_level == ExperienceLevel.SENIOR
        with pytest.raises(ValidationError):
            nl_search.SearchFilters(employment_type="mercenary")

    def test_min_salary_int_coercion(self):
        assert nl_search._coerce_int("90,000") == 90000
        assert nl_search._coerce_int(80000.0) == 80000
        assert nl_search._coerce_int("abc") is None
        assert nl_search._coerce_int(None) is None
        assert nl_search._coerce_int(True) is None


class TestParseFallback:

    def test_fts_fallback_without_provider(self, monkeypatch):
        monkeypatch.setattr(
            "app.services.llm.provider.get_provider", lambda: None
        )
        filters, mode = nl_search.parse_query("remote python jobs in Berlin")
        assert mode == "fts"
        assert filters.keywords == "remote python jobs in Berlin"
        assert filters.skills == []

    def test_empty_query_is_fts(self):
        filters, mode = nl_search.parse_query("   ")
        assert mode == "fts"
        assert filters.keywords is None

    def test_provider_exception_falls_back(self, monkeypatch):
        class Boom:
            def complete_json(self, *a, **k):
                raise RuntimeError("schema never validated")

        monkeypatch.setattr(
            "app.services.llm.provider.get_provider", lambda: Boom()
        )
        filters, mode = nl_search.parse_query("senior data jobs")
        assert mode == "fts"
        assert filters.keywords == "senior data jobs"


class TestHybridRrf:

    def test_rrf_fusion_rewards_cross_list_items(self):
        a = ["j1", "j2", "j3"]
        b = ["j3", "j1", "j2"]
        scores = nl_search.rrf_scores([a, b], k=60)
        # j1 ranks 1st+2nd, j3 ranks 3rd+1st → j1 and j3 both beat j2? compute:
        assert scores["j1"] > scores["j2"]
        assert scores["j3"] > scores["j2"]
        assert scores["j1"] == pytest.approx(
            1 / 61 + 1 / 62, rel=1e-9
        )

    def test_rrf_is_deterministic(self):
        a = ["x", "y", "z"]
        first = nl_search.rrf_scores([a, a])
        second = nl_search.rrf_scores([a, a])
        assert first == second

    def test_hybrid_rank_tie_break_recency_then_id(self, monkeypatch):
        """Tied RRF scores → recency desc, then id asc, input-order stable."""
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        jobs = []
        for day, ident in [(2, "b"), (3, "a"), (2, "a")]:
            job = Job(
                id=uuid4(),
                title=f"Job {ident}{day}",
                description="d",
                location="X",
                is_remote=False,
                created_at=base.replace(day=day),
            )
            jobs.append(job)

        # Force a perfect tie across all candidates so the sort key — not
        # list position — is what's under test.
        monkeypatch.setattr(
            nl_search,
            "rrf_scores",
            lambda lists, k=60: {jid: 1.0 for jid in lists[0]},
        )

        filters = nl_search.SearchFilters()  # no keywords, no skills
        ranked_once = nl_search.hybrid_rank(None, list(jobs), filters)
        ranked_twice = nl_search.hybrid_rank(None, list(reversed(jobs)), filters)

        # tied scores → same output regardless of input order
        assert [j.id for j in ranked_once] == [j.id for j in ranked_twice]

        # newest first overall, id ascending within the same day
        days = [j.created_at for j in ranked_once]
        assert days == sorted(days, reverse=True)
        day2 = [j for j in ranked_once if j.created_at.day == 2]
        assert [str(j.id) for j in day2] == sorted(str(j.id) for j in day2)


class TestNlEndpoint:

    def test_nl_search_endpoint_shape(self):
        resp = client.get("/api/v1/jobs/nl", params={"q": "python developer"})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert set(data) >= {"items", "total", "mode", "parsed_filters", "q"}
        assert data["mode"] in {"llm", "fts"}
        assert data["q"] == "python developer"
        if data["mode"] == "fts":
            # fallback echoes the raw query as the keywords chip
            assert data["parsed_filters"].get("keywords") == "python developer"
        for item in data["items"]:
            score = item["relevance_score"]
            assert score is None or 0.0 <= score <= 100.0

    def test_nl_search_rejects_empty_query(self):
        resp = client.get("/api/v1/jobs/nl", params={"q": ""})
        assert resp.status_code == 422

    def test_canonicalize_drops_unknown_skills(self):
        with SessionLocal() as db:
            filters = nl_search.SearchFilters(skills=["python", "zzznotaskill"])
            out = nl_search.canonicalize_skills(db, filters)
            assert "python" in [s.lower() for s in out.skills]
            assert all("zzz" not in s.lower() for s in out.skills)

    def test_parsed_filters_dict_drops_empties(self):
        filters = nl_search.SearchFilters(
            keywords="data", location=None, skills=[], remote_only=False
        )
        data = nl_search.parsed_filters_dict(filters)
        assert data == {"keywords": "data"}
