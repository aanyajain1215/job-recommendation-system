"""
Resume parsing service.

Two parsing paths:
  1. GeminiResumeParser  — calls Gemini 1.5 Flash with a strict JSON schema prompt.
                           Used when GEMINI_API_KEY is configured.
  2. RegexResumeParser   — heuristic extraction: common-tech-skill keyword matching
                           + date-span regex for years_of_experience estimation.
                           Used as fallback (no external calls, always available).

Public API:
    parse_resume(file_bytes: bytes, extension: str) -> ParsedResume
"""
from __future__ import annotations

import json
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
    parser_used: str = "regex"            # "gemini" | "regex"


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
# Gemini LLM parser
# ---------------------------------------------------------------------------

_GEMINI_PROMPT = """You are a precise resume parsing assistant.
Extract structured information from the resume text below and return ONLY valid JSON matching this exact schema — no markdown, no explanation, nothing else:

{{
  "skills": [
    {{"name": "Python", "category": "programming", "years": 3}},
    ...
  ],
  "years_of_experience": 4.5,
  "seniority": "mid",
  "education": [
    {{"degree": "B.Tech Computer Science", "institution": "IIT Delhi", "year": 2020, "field_of_study": "Computer Science"}}
  ],
  "work_experience": [
    {{"title": "Software Engineer", "company": "Google", "duration_years": 2.0, "description": "Built ML pipelines"}}
  ]
}}

Allowed seniority values: entry, mid, senior, lead, executive
If a field is unknown, use null.
Keep skill names clean canonical strings (e.g. "React" not "reactjs").

RESUME TEXT:
{resume_text}"""


class GeminiResumeParser:
    """LLM-based parser using Gemini 1.5 Flash."""

    def __init__(self, api_key: str) -> None:
        try:
            import google.generativeai as genai  # type: ignore[import-untyped]
            genai.configure(api_key=api_key)
            self._model = genai.GenerativeModel("gemini-1.5-flash")
            self._available = True
        except ImportError:
            logger.warning("google-generativeai not installed; falling back to regex parser.")
            self._available = False

    def parse(self, text: str) -> ParsedResume:
        if not self._available:
            return RegexResumeParser().parse(text)

        prompt = _GEMINI_PROMPT.format(resume_text=text[:12000])  # token budget
        try:
            response = self._model.generate_content(prompt)
            raw = response.text.strip()

            # Strip any accidental markdown fences
            if raw.startswith("```"):
                raw = re.sub(r"^```(?:json)?\s*", "", raw)
                raw = re.sub(r"\s*```$", "", raw)

            data: dict[str, Any] = json.loads(raw)

            skills = [
                ParsedSkill(
                    name=s.get("name", ""),
                    category=s.get("category"),
                    years=s.get("years"),
                )
                for s in data.get("skills", [])
                if s.get("name")
            ]
            education = [
                ParsedEducation(
                    degree=e.get("degree"),
                    institution=e.get("institution"),
                    year=e.get("year"),
                    field_of_study=e.get("field_of_study"),
                )
                for e in data.get("education", [])
            ]
            work_experience = [
                ParsedWorkExperience(
                    title=w.get("title"),
                    company=w.get("company"),
                    duration_years=w.get("duration_years"),
                    description=w.get("description"),
                )
                for w in data.get("work_experience", [])
            ]

            return ParsedResume(
                raw_text=text,
                skills=skills,
                years_of_experience=data.get("years_of_experience"),
                seniority=data.get("seniority"),
                education=education,
                work_experience=work_experience,
                parser_used="gemini",
            )

        except (json.JSONDecodeError, Exception) as exc:
            logger.warning("Gemini parsing failed (%s); falling back to regex.", exc)
            result = RegexResumeParser().parse(text)
            result.parser_used = "regex_fallback"
            return result


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def parse_resume(file_bytes: bytes, extension: str) -> ParsedResume:
    """Extract text from a resume file and return structured data.

    Automatically selects GeminiResumeParser when GEMINI_API_KEY is set,
    otherwise uses RegexResumeParser.
    """
    from app.core.config import get_settings

    text = _extract_text(file_bytes, extension)
    if not text.strip():
        logger.warning("Resume text extraction yielded empty text for extension=%s", extension)
        return ParsedResume(raw_text="", parser_used="regex")

    settings = get_settings()
    if settings.gemini_api_key:
        parser: GeminiResumeParser | RegexResumeParser = GeminiResumeParser(settings.gemini_api_key)
    else:
        parser = RegexResumeParser()

    return parser.parse(text)
