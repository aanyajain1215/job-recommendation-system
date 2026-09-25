"""Resume optimizer (plan §13) — deterministic layer + grounded LLM layer.

Layer 1 (always runs, no LLM): ATS-style report — section presence, length
bounds, keyword coverage vs. the JD, quantified-bullet %, contact block —
plus ``missing_keywords`` (JD requirements absent from the resume) and
``weak_evidence`` (named only in a skills list, never in a bullet).

Layer 2 (LLM prompt P9, optional): bullet critiques/rewrites.  Anti-
fabrication validator (§13, one of the §15 "must not" rails):
- every suggestion must cite a bullet that actually exists in the resume
  (evidence span), and
- every skill token in the rewrite must be in the candidate's own evidence or
  in the JD gap list (labeled "gap — do not claim").
A violation drops the suggestion and increments the flagged-LLM-usage
counter at the call site.  We never add a skill the user hasn't demonstrated.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Iterable

DISCLAIMER = (
    "We will never add a skill you haven't demonstrated. Rewrites cite your "
    "original text; skills outside your evidence are removed automatically."
)

SECTION_PATTERNS: dict[str, re.Pattern[str]] = {
    "summary": re.compile(r"\b(summary|profile|objective)\b", re.I),
    "experience": re.compile(r"\b(experience|employment|work\s+history)\b", re.I),
    "projects": re.compile(r"\b(projects?|portfolio)\b", re.I),
    "skills": re.compile(r"\b(skills|technologies|tech\s+stack)\b", re.I),
}
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_RE = re.compile(r"\+?\d[\d\s().-]{7,}\d")
BULLET_RE = re.compile(r"^\s*(?:[•\-*]|\d+[.)])\s+(.+)$", re.M)

MIN_CHARS = 400
MAX_CHARS = 6000


@dataclass
class AtsCheck:
    name: str
    status: str  # PASS | WARN | FAIL
    detail: str


def extract_bullets(text: str) -> list[str]:
    return [m.group(1).strip() for m in BULLET_RE.finditer(text or "") if m.group(1).strip()]


def _fraction_with_metrics(bullets: list[str]) -> float:
    if not bullets:
        return 0.0
    quantified = sum(1 for b in bullets if re.search(r"\d", b))
    return quantified / len(bullets)


def ats_report(
    resume_text: str,
    *,
    jd_required: list[str],
    bullet_evidence: Iterable[str] = (),
) -> dict[str, Any]:
    """Deterministic ATS report (plan §13 layer 1) — pure function of inputs."""
    text = resume_text or ""
    stripped = text.strip()
    checks: list[AtsCheck] = []

    for name, pattern in SECTION_PATTERNS.items():
        present = bool(pattern.search(text))
        checks.append(
            AtsCheck(
                name=f"section_{name}",
                status="PASS" if present else "FAIL",
                detail=(
                    f"'{name}' section detected"
                    if present
                    else f"No '{name}' section heading found"
                ),
            )
        )

    length = len(stripped)
    if MIN_CHARS <= length <= MAX_CHARS:
        length_status, length_detail = "PASS", f"{length} characters (healthy length)"
    elif length < MIN_CHARS / 2:
        length_status, length_detail = "FAIL", f"Only {length} characters — too thin"
    else:
        length_status, length_detail = "WARN", f"{length} characters (aim for {MIN_CHARS}–{MAX_CHARS})"
    checks.append(AtsCheck(name="length", status=length_status, detail=length_detail))

    lower = text.lower()
    jd_required = [str(s) for s in (jd_required or []) if str(s).strip()]
    present_keywords = [s for s in jd_required if s.lower() in lower]
    missing_keywords = [s for s in jd_required if s.lower() not in lower]
    coverage = (len(present_keywords) / len(jd_required)) if jd_required else 1.0
    if not jd_required:
        cov_status, cov_detail = "PASS", "Job lists no strict keywords"
    elif coverage >= 0.8:
        cov_status, cov_detail = "PASS", f"{coverage:.0%} of required keywords present"
    elif coverage >= 0.5:
        cov_status, cov_detail = "WARN", f"{coverage:.0%} of required keywords present"
    else:
        cov_status, cov_detail = "FAIL", f"{coverage:.0%} of required keywords present"
    checks.append(AtsCheck(name="keyword_coverage", status=cov_status, detail=cov_detail))

    bullets = extract_bullets(text)
    metrics_pct = _fraction_with_metrics(bullets)
    if not bullets:
        bul_status, bul_detail = "WARN", "No list-style bullets detected"
    elif metrics_pct >= 0.4:
        bul_status, bul_detail = "PASS", f"{metrics_pct:.0%} of bullets include a metric"
    else:
        bul_status, bul_detail = "WARN", f"Only {metrics_pct:.0%} of bullets include a metric"
    checks.append(AtsCheck(name="quantified_bullets", status=bul_status, detail=bul_detail))

    has_email = bool(EMAIL_RE.search(text))
    has_phone = bool(PHONE_RE.search(text))
    contact_ok = has_email and has_phone
    contact_detail = (
        "Email and phone present"
        if contact_ok
        else "Missing " + " and ".join(
            [part for part, ok in (("email", has_email), ("phone", has_phone)) if not ok]
        )
    )
    checks.append(
        AtsCheck(
            name="contact_block",
            status="PASS" if contact_ok else "WARN",
            detail=contact_detail,
        )
    )

    # weak evidence: required keyword present only in a skills list, never in a bullet
    bullets_text = "\n".join(bullets).lower()
    weak_evidence = [s for s in present_keywords if s.lower() not in bullets_text]

    passes = sum(1 for c in checks if c.status == "PASS")
    return {
        "checks": [asdict(c) for c in checks],
        "ats_score": round(100.0 * passes / len(checks), 1) if checks else 0.0,
        "missing_keywords": missing_keywords,
        "weak_evidence": weak_evidence,
        "keyword_coverage": round(coverage, 3),
        "quantified_bullet_pct": round(metrics_pct, 3),
        "bullet_count": len(bullets),
    }


# ---------------------------------------------------------------------------
# Anti-fabrication validator (§13 / §15 safety rail)
# ---------------------------------------------------------------------------

def skill_lexicon() -> set[str]:
    """Policable skill vocabulary — the parser's known-tech list (lowercase)."""
    try:
        from app.services.resume_parser import _TECH_SKILLS

        return {str(name).lower() for name, _category in _TECH_SKILLS}
    except Exception:  # pragma: no cover - defensive
        return set()


def tokenize_allowed(values: Iterable[str]) -> set[str]:
    return {str(v).lower().strip() for v in (values or []) if str(v).strip()}


def violating_tokens(
    suggestion: str,
    *,
    allowed: set[str],
    lexicon: set[str],
) -> list[str]:
    """Skill tokens in the rewrite that are neither evidence nor a labeled gap."""
    text = suggestion or ""
    found: list[str] = []
    for token in lexicon:
        if not re.search(rf"\b{re.escape(token)}\b", text, re.I):
            continue
        if token.lower() not in allowed:
            found.append(token)
    return found


def validate_suggestions(
    suggestions: list[dict[str, Any]],
    *,
    original_bullets: Iterable[str],
    allowed_tokens: set[str],
    lexicon: set[str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(kept, violations) — drop any rewrite that fabricates evidence.

    A suggestion survives only if:
    1. ``bullet`` cites an original resume bullet verbatim (span evidence), and
    2. every known-skill token in the rewrite is in ``allowed_tokens``
       (resume evidence ∪ JD gap list labeled "gap — do not claim").
    """
    lexicon = skill_lexicon() if lexicon is None else lexicon
    originals = {b.strip() for b in (original_bullets or []) if b and b.strip()}
    kept: list[dict[str, Any]] = []
    violations: list[dict[str, Any]] = []

    for item in suggestions or []:
        bullet = str(item.get("bullet") or "").strip()
        rewrite = str(item.get("suggestion") or "").strip()
        if not rewrite:
            continue
        if bullet not in originals:
            violations.append({**item, "violation": "bullet_not_in_resume"})
            continue
        bad = violating_tokens(rewrite, allowed=allowed_tokens, lexicon=lexicon)
        if bad:
            violations.append({**item, "violation": "skill_not_in_evidence", "tokens": bad})
            continue
        kept.append(
            {
                "bullet": bullet,
                "issues": list(item.get("issues") or []),
                "rewrite": rewrite,
                "status": "grounded",
            }
        )
    return kept, violations


# ---------------------------------------------------------------------------
# Layer 2 — grounded LLM critique (P9)
# ---------------------------------------------------------------------------

def critique_bullets(
    bullets: list[str],
) -> tuple[list[dict[str, Any]], bool]:
    """P9 bullet critique. Returns ([suggestion dicts], llm_used)."""
    if not bullets:
        return [], False
    try:
        from pydantic import BaseModel, Field

        from app.services.llm.prompts import p9_bullet_critique
        from app.services.llm.provider import get_provider, llm_available
        from app.services.llm.strict import LlmStrictError, strict_bail

        class BulletCritique(BaseModel):
            bullet: str = Field(default="")
            issues: list[str] = Field(default_factory=list)
            suggestion: str = Field(default="")

        class BulletRewrite(BaseModel):
            critiques: list[BulletCritique] = Field(default_factory=list)

        provider = get_provider() if llm_available() else None
        if provider is None:
            strict_bail("resume_optimize", "no LLM provider available")
            return [], False

        result, _usage = provider.complete_json(
            BulletRewrite,
            p9_bullet_critique(bullets),
            route="resume_optimize",
        )
        return [c.model_dump() for c in result.critiques], True
    except LlmStrictError:
        raise
    except Exception as exc:
        strict_bail("resume_optimize", f"LLM critique failed: {exc}")
        return [], False


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def optimize(
    *,
    resume_text: str,
    evidence_tokens: Iterable[str],
    jd_required: Iterable[str],
    gap_skills: Iterable[str],
    profile,
) -> dict[str, Any]:
    """Full §13 response: ATS report + grounded suggestions (or ATS only)."""
    jd_list = [str(s) for s in (jd_required or []) if str(s).strip()]
    evidence = tokenize_allowed(evidence_tokens)
    gaps = tokenize_allowed(gap_skills)

    report = ats_report(resume_text, jd_required=jd_list, bullet_evidence=evidence)

    bullets = extract_bullets(resume_text or "")[:10]
    raw_suggestions, llm_used = critique_bullets(bullets)

    # allowed = own evidence ∪ JD gaps (gaps may be referenced as "gap — do not claim")
    allowed = set(evidence) | set(gaps)
    kept, violations = validate_suggestions(
        raw_suggestions,
        original_bullets=bullets,
        allowed_tokens=allowed,
    )

    return {
        "ats": report,
        "suggestions": kept,
        "violations_dropped": len(violations),
        "llm_used": llm_used,
        "disclaimer": DISCLAIMER,
    }
