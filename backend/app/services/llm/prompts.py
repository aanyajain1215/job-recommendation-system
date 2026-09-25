"""Prompt inventory P1–P10 (plan §15).

Every prompt returns JSON-only instructions; schemas are attached
programmatically by the provider (`_schema_hint`).  Prompts never ask for
scores (the deterministic engine owns numbers) and P5 explicitly demands
digit preservation so the coach prose cannot alter roadmap hours.

| P  | Purpose                                   | Validator(s)        |
|----|-------------------------------------------|---------------------|
| P1 | Resume → structured (+ evidence spans)    | span, skill-token   |
| P2 | JD → structured job requirements          | span, skill-token   |
| P3 | Raw skill strings → canonical + aliases   | skill-token         |
| P4 | Unmatched job title → family              | family enum         |
| P5 | Roadmap numbers → coach prose             | digit-multiset      |
| P6 | Explanation polish (numbers verbatim)     | digit-multiset      |
| P7 | NL query → SearchFilters (whitelisted)    | field whitelist     |
| P8 | Project text → skills + evidence          | span, skill-token   |
| P9 | Bullet critique for resume optimizer      | (structure only)    |
| P10| Skill prerequisite edge proposals         | skill-token         |
"""

from __future__ import annotations

JSON_ONLY = (
    "Respond with ONE valid JSON object only — no markdown fences, "
    "no commentary, no extra fields."
)


def p1_resume(text: str) -> str:
    """Resume → ParsedResume with evidence spans (plan §15/§20)."""
    return f"""You are a precise resume parsing assistant. Extract structured information from the resume text below.

{JSON_ONLY}

Schema (use null for unknown fields):
{{
  "full_name": "Full name as written in the resume header",
  "headline": "professional title stated on the resume (header or stated current role), else null",
  "summary": "the resume's own summary/objective paragraph, lightly trimmed, else null",
  "location": "city/location written on the resume, else null",
  "phone": "phone number exactly as written, else null",
  "skills": [{{"name": "Python", "category": "programming", "years": 3}}],
  "years_of_experience": 4.5,
  "seniority": "entry | mid | senior | lead | executive",
  "education": [{{"degree": "...", "institution": "...", "year": 2020, "field_of_study": "..."}}],
  "work_experience": [{{"title": "...", "company": "...", "start_date": "2021-06", "end_date": "2023-02", "location": "...", "duration_years": 2.0, "description": "..."}}],
  "evidence": [{{"skill": "Python", "start": 12, "end": 18, "quote": "Python"}}],
  "projects": [{{"name": "...", "description": "...", "skills": ["React"]}}],
  "certifications": [{{"name": "...", "issuer": "...", "year": 2023}}],
  "interests": ["machine learning"]
}}

Rules:
- Every evidence.quote MUST be a verbatim substring of the resume text, and [start:end] MUST slice to exactly that quote.
- NEVER invent skills, dates, employers, degrees or numbers that are not in the text.
- full_name, phone, location, start_date and end_date must be copied verbatim from the text; use null when not present.
- summary must be the resume's own summary/objective wording — never rewritten or padded; null if the resume has none.
- Keep skill names clean canonical strings (e.g. "React", not "reactjs").

RESUME TEXT:
{text[:12000]}"""


def p2_job_description(text: str) -> str:
    """JD → structured requirements (plan §15/§20.1 stage 3)."""
    return f"""You are a job-posting structuring assistant.

{JSON_ONLY}

Schema:
{{
  "title": "Senior Backend Engineer",
  "seniority": "entry | mid | senior | lead | executive",
  "experience_years_min": 3,
  "required_skills": [{{"name": "Python", "importance": 1.6}}],
  "preferred_skills": [{{"name": "Docker", "importance": 1.0}}],
  "degree": null,
  "field": null,
  "industry": null
}}

Rules:
- Extract skills ONLY from text present in the posting (span-checkable) or from well-known canonical names.
- importance must be between 0.5 and 1.6 (required skills should be >= 1.4).
- NEVER invent requirements the posting does not state.

JOB POSTING TEXT:
{text[:8000]}"""


def p3_skill_proposal(raw_skills: list[str]) -> str:
    """Raw skill strings → canonical candidates + proposed aliases (P3)."""
    joined = ", ".join(raw_skills[:200])
    return f"""You are a skill-taxonomy assistant mapping raw skill strings to canonical names.

{JSON_ONLY}

Schema:
{{
  "proposals": [
    {{"raw": "ReactJS", "canonical": "React", "alias_of": "React", "confidence": 0.95}}
  ]
}}

Rules:
- canonical = an existing canonical name when one clearly exists, else a clean new name.
- alias_of is set only when raw is an alias of an existing canonical skill.
- confidence in [0, 1]; be conservative (>= 0.9 only for unambiguous matches).

RAW SKILL STRINGS:
{joined}"""


def p4_title_to_family(title: str, allowed: list[str]) -> str:
    """Unmatched job title → family, validated against the family set (P4)."""
    return f"""You are a job-family classification assistant.

{JSON_ONLY}

Schema:
{{"family": "<one of the allowed families>"}}

Allowed families: {allowed}

Rules:
- Respond with exactly one allowed family name.
- If nothing fits, respond with "other".

JOB TITLE:
{title}"""


def p5_roadmap_coach(sections: dict) -> str:
    """Roadmap numbers → coach prose. Digit-preservation is mandatory (P5)."""
    import json as _json

    return f"""You are a career coach writing a short, encouraging roadmap summary.

{JSON_ONLY}

Schema:
{{
  "headline": "one sentence",
  "phase_notes": [{{"label": "Phase 1", "note": "2-3 sentences"}}],
  "closing": "one sentence"
}}

Rules:
- The numbers below are ground truth and MUST appear EXACTLY as given (hours, counts, bands). Never round, add, subtract or invent numbers.
- Use every hour figure exactly as written.

ROADMAP DATA (ground truth):
{_json.dumps(sections, ensure_ascii=False)}"""


def p6_explanation_polish(summary: str, numbers: list[str]) -> str:
    """Explanation polish — may rewrite wording only, never numbers (P6)."""
    return f"""You are an assistant polishing a job-match explanation sentence.

{JSON_ONLY}

Schema:
{{"sentences": ["polished summary"], "recommended_action": "one actionable sentence"}}

Rules:
- Keep these exact strings untouched wherever they appear: {numbers}
- Plain, specific, no hype words ("amazing", "perfect"), max 45 words total.

SOURCE SUMMARY:
{summary}"""


def p7_nl_search(query: str) -> str:
    """NL query → SearchFilters — whitelisted fields/enums only (P7)."""
    return f"""You are a search-filter assistant converting a natural-language job query into strict JSON filters.

{JSON_ONLY}

Schema:
{{
  "keywords": "free text or null",
  "location": "city name or null",
  "remote_only": true,
  "employment_type": "full_time | part_time | contract | internship | temporary | null",
  "experience_level": "entry | mid | senior | lead | executive | null",
  "min_salary": 0,
  "skills": ["Python"]
}}

Rules:
- ONLY include fields the user's query actually mentions (unknown fields are dropped downstream anyway).
- Use ONLY the enum values listed. Never invent fields.

USER QUERY:
{query}"""


def p8_project_skills(text: str) -> str:
    """Project text → skills + evidence (plan §14)."""
    return f"""You are a project-skill extraction assistant.

{JSON_ONLY}

Schema:
{{
  "skills": ["React", "PostgreSQL"],
  "evidence": [{{"skill": "React", "start": 0, "end": 5, "quote": "React"}}],
  "blurb": "one-sentence project summary"
}}

Rules:
- Skills MUST appear verbatim in the project text (evidence.quote must be a substring, [start:end] must slice to it).
- Never invent technologies.

PROJECT TEXT:
{text[:6000]}"""


def p9_bullet_critique(bullets: list[str]) -> str:
    """Bullet critique for the resume optimizer (P9)."""
    joined = "\n".join(f"- {b}" for b in bullets[:20])
    return f"""You are a resume writing coach critiquing experience bullets.

{JSON_ONLY}

Schema:
{{
  "critiques": [
    {{"bullet": "<original>", "issues": ["no metric"], "suggestion": "rewritten bullet"}}
  ]
}}

Rules:
- Never invent employers, tools or outcomes — suggest structure/metrics placeholders like "[metric]" instead.
- Keep the candidate's real claims intact.

BULLETS:
{joined}"""


def p10_edge_proposal(src: str, dst: str, context: str = "") -> str:
    """Skill prerequisite edge proposals → source=LLM, approved=false (P10)."""
    return f"""You are a skill-graph curation assistant proposing prerequisite edges.

{JSON_ONLY}

Schema:
{{
  "proposals": [
    {{"from": "python", "to": "fastapi", "type": "prereq | transfer | supersedes", "weight": 0.8, "confidence": 0.9, "rationale": "one sentence"}}
  ]
}}

Rules:
- weight in (0, 1]; confidence in [0, 1].
- Only propose edges you are confident about (confidence >= 0.8).
- Never propose self-edges.

CANDIDATE PAIR:
from: {src}
to: {dst}
context: {context}"""


# Catalog for docs/admin surfaces (plan §15 table)
PROMPT_CATALOG: dict[str, str] = {
    "P1": "Resume → structured (+ evidence spans, projects, certifications, interests)",
    "P2": "JD → structured (title, skills w/ importance, exp/edu, seniority)",
    "P3": "Raw skill strings → canonical candidates + proposed aliases",
    "P4": "Unmatched job title → family (validated against family enum)",
    "P5": "Roadmap numbers → coach prose (digit-preservation validator)",
    "P6": "Explanation polish (numbers verbatim)",
    "P7": "NL query → SearchFilters (whitelisted fields/enums only)",
    "P8": "Project text → skills + evidence",
    "P9": "Bullet critique for resume optimizer",
    "P10": "Skill prerequisite edge proposals → skill_edges(source=LLM)",
}
