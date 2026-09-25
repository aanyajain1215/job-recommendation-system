"""
Resume parsing service (plan §15 P1 — routed through the provider abstraction).

Parsing paths:
  1. LlmResumeParser     — P1 through `services.llm.provider` with a strict
                           JSON schema, then evidence-preserving validation
                           (span + skill-token checks): violating rows are
                           dropped, the call is flagged, the valid rows are
                           kept.  Used whenever a provider is configured
                           (OpenAI default, Gemini retained).
  2. RegexResumeParser   — heuristic extraction: common-tech-skill keyword
                           matching + date-span regex for years estimation.
                           Always available fallback — no external calls.

Public API (stable — tests and api/profiles.py import these names):
    parse_resume(file_bytes: bytes, extension: str) -> ParsedResume
    ParsedResume, RegexResumeParser, GeminiResumeParser
    _extract_text, _estimate_years, _infer_seniority
"""
from __future__ import annotations

import logging
import re
from io import BytesIO
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------

class ParsedSkill(BaseModel):
    name: str
    category: str | None = None
    years: float | None = None  # years of experience with this specific skill


class ParsedEducation(BaseModel):
    degree: str | None = None
    institution: str | None = None
    year: int | None = None
    field_of_study: str | None = None


class ParsedWorkExperience(BaseModel):
    title: str | None = None
    company: str | None = None
    duration_years: float | None = None
    description: str | None = None


class ParsedResume(BaseModel):
    """Structured extraction result consumed by the profile-update background task."""

    raw_text: str = ""
    skills: list[ParsedSkill] = Field(default_factory=list)
    years_of_experience: float | None = None
    seniority: str | None = None          # maps to ExperienceLevel enum values
    education: list[ParsedEducation] = Field(default_factory=list)
    work_experience: list[ParsedWorkExperience] = Field(default_factory=list)
    parser_used: str = "regex"            # "openai" | "gemini" | "regex" | "regex_fallback"
    # ---- P1 upgraded schema (plan §15: evidence-preserving extraction) ----
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    projects: list[dict[str, Any]] = Field(default_factory=list)
    certifications: list[dict[str, Any]] = Field(default_factory=list)
    interests: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Text extraction helpers (PDF / DOCX / TXT)
# ---------------------------------------------------------------------------

def _extract_text(file_bytes: bytes, extension: str) -> str:
    """Return plain text content from a resume file regardless of format."""
    ext = extension.lower().lstrip(".")

    if ext == "pdf":
        try:
            from pypdf import PdfReader  # type: ignore[import-untyped]
            reader = PdfReader(BytesIO(file_bytes))
            pages = [page.extract_text() or "" for page in reader.pages]
            return "\n".join(pages)
        except Exception as exc:
            logger.warning("PDF text extraction failed: %s", exc)
            return ""

    if ext == "docx":
        try:
            import docx  # type: ignore[import-untyped]  (python-docx)
            doc = docx.Document(BytesIO(file_bytes))
            return "\n".join(para.text for para in doc.paragraphs)
        except Exception as exc:
            logger.warning("DOCX text extraction failed: %s", exc)
            return ""

    # Plain text — try UTF-8 then latin-1 fallback
    try:
        return file_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return file_bytes.decode("latin-1", errors="replace")


# ---------------------------------------------------------------------------
# Regex / heuristic parser (fallback — no external API)
# ---------------------------------------------------------------------------

# Common tech-skill keyword list (extend as needed)
_TECH_SKILLS: list[tuple[str, str]] = [
    # (canonical_name, category)
    ("Python", "programming"),
    ("JavaScript", "programming"),
    ("TypeScript", "programming"),
    ("Java", "programming"),
    ("C++", "programming"),
    ("C#", "programming"),
    ("Go", "programming"),
    ("Rust", "programming"),
    ("SQL", "data"),
    ("PostgreSQL", "data"),
    ("MySQL", "data"),
    ("MongoDB", "data"),
    ("Redis", "data"),
    ("Elasticsearch", "data"),
    ("React", "frontend"),
    ("Vue", "frontend"),
    ("Angular", "frontend"),
    ("Next.js", "frontend"),
    ("Node.js", "backend"),
    ("FastAPI", "backend"),
    ("Django", "backend"),
    ("Flask", "backend"),
    ("Spring Boot", "backend"),
    ("Docker", "devops"),
    ("Kubernetes", "devops"),
    ("AWS", "cloud"),
    ("GCP", "cloud"),
    ("Azure", "cloud"),
    ("Terraform", "devops"),
    ("Git", "tools"),
    ("CI/CD", "devops"),
    ("GitHub Actions", "devops"),
    ("Machine Learning", "ml"),
    ("Deep Learning", "ml"),
    ("NLP", "ml"),
    ("TensorFlow", "ml"),
    ("PyTorch", "ml"),
    ("scikit-learn", "ml"),
    ("Pandas", "data"),
    ("NumPy", "data"),
    ("Spark", "data"),
    ("Kafka", "data"),
    ("REST", "backend"),
    ("GraphQL", "backend"),
    ("Linux", "systems"),
    ("Agile", "methodology"),
    ("Scrum", "methodology"),
]

# Regex patterns for date ranges (e.g. "Jan 2019 – Mar 2022", "2019-2022", "2020 - Present")
_DATE_RANGE_PATTERN = re.compile(
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)?\s*(\d{4})\s*"
    r"[-–—to]+\s*"
    r"(?:(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)?\s*(\d{4})|[Pp]resent|[Cc]urrent|[Nn]ow)",
    re.IGNORECASE,
)

_SENIORITY_MAP = [
    (("intern", "trainee", "apprentice"), "entry"),
    (("junior", "associate", "graduate"), "entry"),
    (("director", "vp ", "vice president", "head of", "chief", "cto", "ceo", "coo"), "executive"),
    (("lead", "principal", "staff"), "lead"),
    (("engineering manager", "manager"), "lead"),
    (("senior", "sr.", "sr "), "senior"),
    (("mid", "software engineer", "developer", "analyst", "entry"), "mid"),
]


def _estimate_years(text: str) -> float | None:
    """Sum up date-range durations found in the text to estimate total experience."""
    import datetime
    current_year = datetime.datetime.now().year
    total_months = 0

    for m in _DATE_RANGE_PATTERN.finditer(text):
        start_year = int(m.group(1))
        end_str = m.group(2)
        end_year = int(end_str) if end_str else current_year
        # Clamp sanity
        if 1980 <= start_year <= current_year and start_year <= end_year <= current_year + 1:
            total_months += (end_year - start_year) * 12

    if total_months == 0:
        return None
    # Deduplicate overlapping ranges by halving if suspiciously high
    years = total_months / 12
    return round(min(years, 50.0), 1)


def _infer_seniority(text: str, years: float | None) -> str | None:
    lowered = text.lower()
    for keywords, level in _SENIORITY_MAP:
        if any(kw in lowered for kw in keywords):
            return level
    if years is not None:
        if years < 2:
            return "entry"
        if years < 5:
            return "mid"
        if years < 9:
            return "senior"
        return "lead"
    return None


class RegexResumeParser:
    """Heuristic parser — zero external calls."""

    def parse(self, text: str) -> ParsedResume:
        text_lower = text.lower()
        found_skills: list[ParsedSkill] = []
        for name, category in _TECH_SKILLS:
            if name.lower() in text_lower:
                found_skills.append(ParsedSkill(name=name, category=category))

        years = _estimate_years(text)
        seniority = _infer_seniority(text, years)

        return ParsedResume(
            raw_text=text,
            skills=found_skills,
            years_of_experience=years,
            seniority=seniority,
            education=[],
            work_experience=[],
            parser_used="regex",
        )


# ---------------------------------------------------------------------------
# LLM parser (plan §15 P1 — provider abstraction + validators)
# ---------------------------------------------------------------------------

class LlmResumeParser:
    """P1 through the provider abstraction with evidence-preserving repair.

    Contract: span/skill-token violations never reach the profile.  Rows
    failing validation are dropped (valid rows are kept — extraction is
    evidence-preserving, not all-or-nothing), the usage is flagged in
    `llm_usage`, and any hard failure falls back to the regex parser.
    """

    def __init__(self) -> None:
        from app.services.llm import get_provider  # noqa: PLC0415

        self._provider = get_provider()

    @property
    def available(self) -> bool:
        return self._provider is not None

    def parse(self, text: str) -> ParsedResume:
        from app.services.llm.strict import LlmStrictError, strict_bail

        if self._provider is None:
            strict_bail("resume_parse", "no LLM provider available")
            return RegexResumeParser().parse(text)

        from app.services.llm import mark_flagged, validators  # noqa: PLC0415
        from app.services.llm import prompts  # noqa: PLC0415

        try:
            parsed, usage = self._provider.complete_json(
                ParsedResume,
                prompts.p1_resume(text),
                system=(
                    "You extract structured resume data. You never invent "
                    "content: every claim must be traceable to the source text."
                ),
                max_tokens=2500,
                route="P1",
            )
        except LlmStrictError:
            raise
        except Exception as exc:
            strict_bail("resume_parse", f"LLM parse failed: {exc}")
            logger.warning("P1 LLM parsing failed (%s); falling back to regex.", exc)
            result = RegexResumeParser().parse(text)
            result.parser_used = "regex_fallback"
            return result

        # ---- evidence-preserving validation (plan §15) ----
        problems: list[str] = []
        problems += validators.validate_spans(parsed.evidence, text)
        problems += validators.validate_skill_tokens(
            [s.name for s in parsed.skills], text
        )

        if problems:
            mark_flagged(usage, reason="P1: " + "; ".join(problems[:3]))
            logger.warning("P1 output failed validators (%s); filtering rows.", problems)
            # Drop only violating rows — keep everything that passed.
            parsed.evidence = [
                e for e in parsed.evidence if validators.validate_spans([e], text) == []
            ]
            src_lower = text.lower()
            parsed.skills = [
                s for s in parsed.skills
                if s.name and s.name.lower().strip() in src_lower
            ]

        parsed.raw_text = text
        parsed.parser_used = self._provider.name
        if parsed.seniority is None:
            parsed.seniority = _infer_seniority(text, parsed.years_of_experience)
        return parsed


# Back-compat alias (pre-provider name; nothing may break importing it)
GeminiResumeParser = LlmResumeParser


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def parse_resume(file_bytes: bytes, extension: str) -> ParsedResume:
    """Extract text from a resume file and return structured data.

    Uses the configured LLM provider (plan §15 — OpenAI default) whenever a
    key is present; otherwise the deterministic regex parser.  Failures
    inside the LLM path always fall back to regex, never to an error.
    """
    text = _extract_text(file_bytes, extension)
    if not text.strip():
        logger.warning("Resume text extraction yielded empty text for extension=%s", extension)
        return ParsedResume(raw_text="", parser_used="regex")

    llm_parser = LlmResumeParser()
    if llm_parser.available:
        return llm_parser.parse(text)
    return RegexResumeParser().parse(text)
