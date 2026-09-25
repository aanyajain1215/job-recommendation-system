"""Auto-fill-from-resume contract tests (plan §15 P1 identity extraction).

Covers:
- Regex identity heuristics (full_name / phone) — hermetic, zero LLM calls.
- ParsedResume identity + work-date schema fields.
- P1 prompt keeps pace with the schema (identity keys present).
- LLM identity guard: unverifiable full_name/phone are dropped, never trusted.
- POST /profiles/me/resume exposes parsed_resume_data.autofill + the resume
  row's parse_status while leaving identity profile columns untouched
  (the form fills; only the user's Save persists them).
- POST /profiles/me/resume/reparse recovery paths.
"""

from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.profiles import UPLOAD_DIR
from app.core.db import SessionLocal
from app.main import app
from app.models.profile import Profile
from app.models.profile_entities import Resume
from app.models.user import User
from app.services.llm import prompts
from app.services.resume_parser import (
    LlmResumeParser,
    ParsedResume,
    RegexResumeParser,
    _extract_name,
    _extract_phone,
)

client = TestClient(app, raise_server_exceptions=False)

RESUME_TEXT = b"""Aanya Jain
+91 98765 43210 | Bengaluru, India

Summary
Python and FastAPI developer with 3 years of experience building job platforms.

Experience
Software Engineer at Acme Corp (2021 - 2024)
Skills: Python, FastAPI, React, Docker, PostgreSQL
"""


# ---------------------------------------------------------------------------
# Hermetic parser-level tests (regex path — no provider, no quota)
# ---------------------------------------------------------------------------

def test_regex_parser_extracts_identity():
    result = RegexResumeParser().parse(RESUME_TEXT.decode("utf-8"))
    assert result.full_name == "Aanya Jain"
    assert result.phone == "+91 98765 43210"
    assert any(s.name == "Python" for s in result.skills)
    assert result.parser_used == "regex"


def test_name_heuristic_skips_headings_and_contacts():
    assert _extract_name("Aanya Jain") == "Aanya Jain"
    # Section headings, contacts and locations must never become a "name".
    assert _extract_name("Work Experience") is None
    assert _extract_name("Contact Info") is None
    assert _extract_name("aanya@example.com") is None
    assert _extract_name("9876543210") is None
    assert _extract_name("Bengaluru, India") is None  # comma → location line


def test_phone_heuristic_handles_real_formats_and_rejects_years():
    assert _extract_phone("+91 98765 43210") == "+91 98765 43210"
    assert _extract_phone("+1 (555) 123-4567") is not None
    assert _extract_phone("011-2345-6789") is not None
    assert _extract_phone("call me on 9876543210") is not None
    # Year ranges must never be mistaken for a phone number.
    assert _extract_phone("2019 - 2022 at Google") is None
    assert _extract_phone("Jun 2019 - Aug 2022") is None
    assert _extract_phone("built in 2019-2022") is None


def test_parsed_resume_schema_accepts_identity_fields():
    parsed = ParsedResume(
        full_name="Jane Doe",
        headline="Software Engineer",
        summary="Builder of things.",
        location="Pune, India",
        phone="+1 555 0100",
    )
    assert parsed.full_name == "Jane Doe"
    assert parsed.phone == "+1 555 0100"
    assert ParsedResume().full_name is None


def test_work_experience_schema_has_dates_for_form_fill():
    parsed = ParsedResume(
        work_experience=[{"title": "SWE", "company": "Acme", "start_date": "2021-06"}]
    )
    assert parsed.work_experience[0].start_date == "2021-06"
    assert parsed.work_experience[0].end_date is None


def test_p1_prompt_documents_identity_and_dates():
    prompt = prompts.p1_resume("Software Engineer with Python")
    for key in (
        '"full_name"',
        '"headline"',
        '"summary"',
        '"location"',
        '"phone"',
        '"start_date"',
        '"end_date"',
        "never rewritten",
    ):
        assert key in prompt, f"P1 prompt missing {key}"


# ---------------------------------------------------------------------------
# LLM-path identity guard (fake provider — still zero quota)
# ---------------------------------------------------------------------------

class _FakeProvider:
    name = "fake"

    def __init__(self, parsed: ParsedResume) -> None:
        self._parsed = parsed

    def complete_json(self, schema, prompt, system=None, max_tokens=0, route=""):
        usage = {
            "provider": "fake",
            "model": "fake",
            "route": route,
            "prompt_tokens": 1,
            "completion_tokens": 1,
            "latency_ms": 1,
        }
        return self._parsed, usage


def _llm_parser_with(parsed: ParsedResume) -> LlmResumeParser:
    parser = LlmResumeParser()  # conftest stubs get_provider → None
    parser._provider = _FakeProvider(parsed)  # inject fake; no network, no quota
    return parser


def test_llm_identity_fields_must_be_traceable_to_source():
    parser = _llm_parser_with(
        ParsedResume(
            full_name="Invented Person",   # not in source → must be dropped
            phone="+1 000 000 0000",       # digits not in source → dropped
            skills=[],
        )
    )
    result = parser.parse(RESUME_TEXT.decode("utf-8"))
    assert result.full_name is None
    assert result.phone is None
    assert result.parser_used == "fake"


def test_llm_identity_fields_kept_when_present_in_source():
    parser = _llm_parser_with(
        ParsedResume(
            full_name="Aanya Jain",
            phone="+91 98765 43210",
            headline="Software Engineer",
            skills=[],
        )
    )
    result = parser.parse(RESUME_TEXT.decode("utf-8"))
    assert result.full_name == "Aanya Jain"
    assert result.phone == "+91 98765 43210"
    assert result.headline == "Software Engineer"


# ---------------------------------------------------------------------------
# HTTP contract (TestClient: background tasks run synchronously)
# ---------------------------------------------------------------------------

def _register_seeker() -> dict:
    uid = uuid4().hex[:8]
    reg = client.post(
        "/api/v1/auth/register",
        json={
            "email": f"autofill_{uid}@example.com",
            "password": "Password123!",
            "role": "job_seeker",
        },
    )
    assert reg.status_code == 201, reg.text
    body = reg.json()
    return {
        "headers": {"Authorization": f"Bearer {body['access_token']}"},
        "id": body["user"]["id"],
    }


def _delete_seeker(user_id) -> None:
    """Purge stored resume files, resume rows, then the account."""
    with SessionLocal() as db:
        uid = UUID(str(user_id))
        profile = db.scalar(select(Profile).where(Profile.user_id == uid))
        if profile is not None:
            for resume in db.scalars(
                select(Resume).where(Resume.profile_id == profile.id)
            ).all():
                if resume.file_path:
                    try:
                        (UPLOAD_DIR / resume.file_path).unlink(missing_ok=True)
                    except OSError:
                        pass
                db.delete(resume)
        row = db.get(User, uid)
        if row is not None:
            db.delete(row)  # profile + children cascade (existing test pattern)
        db.commit()


@pytest.fixture
def seeker():
    account = _register_seeker()
    yield account
    _delete_seeker(account["id"])


def _upload(seeker: dict) -> None:
    resp = client.post(
        "/api/v1/profiles/me/resume",
        headers=seeker["headers"],
        files={"file": ("resume.txt", RESUME_TEXT, "text/plain")},
    )
    assert resp.status_code == 200, resp.text


def test_upload_parse_exposes_autofill_without_touching_identity(seeker):
    # Ensure the profile row exists (upload 404s without one).
    assert client.get("/api/v1/profiles/me", headers=seeker["headers"]).status_code == 200

    _upload(seeker)

    prof = client.get("/api/v1/profiles/me", headers=seeker["headers"]).json()
    # Background parse ran synchronously under TestClient.
    assert prof["resumes"][0]["parse_status"] == "parsed"
    assert prof["resumes"][0]["parser_used"] == "regex"

    af = (prof.get("parsed_resume_data") or {}).get("autofill") or {}
    assert af.get("full_name") == "Aanya Jain"
    assert af.get("phone") == "+91 98765 43210"
    assert af.get("headline") is None  # regex path cannot extract it — honest null

    # Existing behavior preserved: skills land in the profile.
    assert any(s["skill_name"] == "Python" for s in prof["skills"])

    # Contract: the parse must NOT write identity columns — the user reviews
    # the filled form and persists via PUT /profiles/me.
    assert prof["first_name"] == ""
    assert prof["last_name"] == ""
    assert prof["headline"] is None
    assert prof["bio"] is None
    assert prof["location"] is None
    assert prof["phone"] is None


def test_reparse_requires_stored_resume(seeker):
    assert client.get("/api/v1/profiles/me", headers=seeker["headers"]).status_code == 200
    resp = client.post("/api/v1/profiles/me/resume/reparse", headers=seeker["headers"])
    assert resp.status_code == 400
    assert "No resume" in resp.json()["detail"]


def test_reparse_reruns_parse_on_stored_file(seeker):
    assert client.get("/api/v1/profiles/me", headers=seeker["headers"]).status_code == 200
    _upload(seeker)

    resp = client.post("/api/v1/profiles/me/resume/reparse", headers=seeker["headers"])
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "parsing"

    # The synchronous background task has completed by the time TestClient
    # returns; a fresh GET shows the final state.
    prof = client.get("/api/v1/profiles/me", headers=seeker["headers"]).json()
    assert prof["resumes"][0]["parse_status"] == "parsed"
    af = (prof.get("parsed_resume_data") or {}).get("autofill") or {}
    assert af.get("full_name") == "Aanya Jain"
