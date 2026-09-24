"""Ingestion pipeline tests (plan §20.1) — offline, no network, no DB writes.

Covers stages 2–5 (clean/parse/structure/gates/dedupe) plus the full offline
pipeline over the committed golden corpus with a temp snapshot destination.
"""

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend/
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://x:x@localhost:55432/x")

from app.services.ingest import (  # noqa: E402
    DedupeBook,
    clean_text,
    map_seniority,
    normalize_signature,
    parse_salary,
    parse_years,
    quality_gates,
)
from app.services.ingest.parse import (  # noqa: E402
    detect_employment_type,
    detect_remote,
    parse_location,
)
from scripts.fetch_jobs_live import (  # noqa: E402
    assign_family,
    extract_skills,
    load_families,
    load_surface_pairs,
    run_pipeline,
)

BACKEND = Path(__file__).resolve().parents[1]
GOLDEN = BACKEND / "ml" / "data" / "golden" / "postings.jsonl"


def _ensure_golden() -> list[dict]:
    if not GOLDEN.exists():
        from scripts.synthesize_corpus import build_all  # noqa: PLC0415

        build_all()
    with GOLDEN.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


# ---------------------------------------------------------------------------
# Stage 2 — clean
# ---------------------------------------------------------------------------

def test_clean_text_strips_html_entities_and_eeo():
    raw = (
        "<p>We build things</p><br>Great &amp; small teams\n"
        "We are an equal opportunity employer and all qualified "
        "applicants will receive consideration.\n"
        "Ship  fast."
    )
    out = clean_text(raw)
    assert "<p>" not in out and "</br>" not in out
    assert "&amp;" not in out and "Great & small teams" in out
    assert "equal opportunity" not in out.lower()
    assert "Ship fast." in out


def test_clean_text_empty_input():
    assert clean_text(None) == ""
    assert clean_text("   \n  ") == ""


# ---------------------------------------------------------------------------
# Stage 3 — parse
# ---------------------------------------------------------------------------

def test_parse_salary_variants():
    assert parse_salary("$90,000 - $120,000") == (90000, 120000, "USD")
    assert parse_salary("₹15,00,000 – ₹22,00,000") == (1500000, 2200000, "INR")
    assert parse_salary("90k - 130k USD") == (90000, 130000, "USD")
    assert parse_salary("€60,000 to €85,000") == (60000, 85000, "EUR")
    # no evidence → never fabricated
    assert parse_salary("2015 - 2019") == (None, None, None)
    assert parse_salary("Competitive package offered") == (None, None, None)
    assert parse_salary("") == (None, None, None)


def test_parse_years():
    assert parse_years("You bring 5+ years of experience") == 5.0
    assert parse_years("experience of 5-7 years needed") == 5.0
    assert parse_years("worked closely for 3 years") == 3.0
    assert parse_years("no duration here") is None
    assert parse_years("") is None


def test_map_seniority_keywords():
    assert map_seniority("Senior Backend Engineer").value == "senior"
    assert map_seniority("Junior Developer").value == "entry"
    assert map_seniority("DevOps Intern").value == "entry"
    assert map_seniority("Lead Platform Engineer").value == "lead"
    assert map_seniority("CTO").value == "executive"


def test_parse_location_and_flags():
    assert parse_location("  Bengaluru ,  India ") == "Bengaluru , India"
    assert parse_location(None) is None
    assert detect_remote("Backend Engineer", "Fully remote team", None) is True
    assert detect_remote("Onsite Role", "Five days in office", "Austin") is False
    assert detect_employment_type("12 month contract role").value == "contract"
    assert detect_employment_type("Full-time position").value == "full_time"
    assert detect_employment_type("Summer internship").value == "internship"


# ---------------------------------------------------------------------------
# Stage 5 — gates + dedupe
# ---------------------------------------------------------------------------

def test_quality_gates():
    good = {"title": "Backend Engineer", "description": "x" * 150,
            "salary_min": 10, "salary_max": 20}
    assert quality_gates(good) == []
    assert any("description_too_short" in p
               for p in quality_gates({**good, "description": "tiny"}))
    assert any("empty_title" in p for p in quality_gates({**good, "title": "   "}))
    assert "salary_min_gt_salary_max" in quality_gates(
        {**good, "salary_min": 90, "salary_max": 10}
    )


def test_dedupe_book_external_and_signature():
    book = DedupeBook()
    assert book.duplicate_reason("adzuna", "1", "Backend Engineer", "Acme") is None
    book.remember("adzuna", "1", "Backend Engineer", "Acme")
    # same source + external id
    assert book.duplicate_reason("adzuna", "1", "Other Title", "X") is not None
    # cross-source signature (case/punctuation-insensitive)
    assert book.duplicate_reason("remotive", "9", "backend   engineer!", "ACME") is not None
    # genuinely different
    assert book.duplicate_reason("remotive", "8", "Data Analyst", "Other") is None
    assert normalize_signature("Backend, Engineer!!", "ACME") == "backend engineer acme"


# ---------------------------------------------------------------------------
# Stage 4 — structure (skills + family)
# ---------------------------------------------------------------------------

def test_extract_skills_required_vs_nice_to_have():
    pairs = [("react", "React"), ("kubernetes", "Kubernetes"),
             ("docker", "Docker")]
    title = "Frontend Engineer"
    desc = "Requirements:\n- React\n- Docker\nNice to have:\n- Kubernetes"
    got = {name: required for name, required in extract_skills(title, desc, pairs)}
    assert got["React"] is True
    assert got["Docker"] is True
    assert got["Kubernetes"] is False   # only appears after the marker


def test_extract_skills_word_boundaries():
    pairs = [("java", "Java"), ("javascript", "JavaScript"), ("go", "Go")]
    got = {n for n, _ in extract_skills("Engineer", "We use JavaScript daily.", pairs)}
    assert "JavaScript" in got
    assert "Java" not in got          # boundary prevents prefix matches
    got2 = {n for n, _ in extract_skills("Engineer", "We use Django here.", pairs)}
    assert "Go" not in got2           # lookbehind blocks substrings


def test_assign_family_deepest_first():
    families = load_families()
    assert assign_family("Senior Backend Engineer", families) == "Backend Engineering"
    assert assign_family("Machine Learning Engineer", families) == (
        "Machine Learning Engineering"
    )
    assert assign_family("Data Analyst", families) == "Data Analytics"
    assert assign_family("Growth Hacker", families) is None


# ---------------------------------------------------------------------------
# Full offline pipeline (stages 2–7, no DB)
# ---------------------------------------------------------------------------

def test_offline_pipeline_end_to_end(tmp_path):
    postings = _ensure_golden()
    assert len(postings) == 100

    result = run_pipeline(postings, dest=tmp_path, mode="offline")
    report = result["report"]

    assert report["fetched"] == 100
    assert report["cleaned"] == 100
    assert report["parsed"] == 100
    assert report["gate_failed"] == 5          # the five too-short postings
    assert report["dup_skipped"] == 4          # duplicate signatures
    assert report["snapshot_rows"] == 91
    assert report["family_unassigned"] >= 3    # the deliberately odd titles
    assert report["no_skill_flagged"] >= 1

    # snapshot is valid JSONL of the kept rows
    snapshot = Path(result["snapshot"])
    assert snapshot.exists()
    kept = [json.loads(line) for line in snapshot.read_text(encoding="utf-8").splitlines()]
    assert len(kept) == 91
    assert all(row["description"].find("<p>") == -1 for row in kept)
    assert all("equal opportunity" not in row["description"].lower() for row in kept)
    assert any(row["family"] == "Backend Engineering" for row in kept)
    assert sum(1 for row in kept if row["skills"]) >= 80

    # run report written + machine readable
    run_report = Path(result["run_report"])
    assert run_report.exists()
    parsed = json.loads(run_report.read_text(encoding="utf-8"))
    assert parsed["snapshot_rows"] == 91


def test_surface_pairs_cover_canonical_skills():
    pairs = load_surface_pairs()
    surfaces = {surface for surface, _canonical in pairs}
    assert "python" in surfaces
    assert "k8s" in surfaces          # alias resolves to Kubernetes
    assert "machine learning" in surfaces
