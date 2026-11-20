"""Stage 3 — structured field parsing (plan §20.1).

Deterministic extractors for location, salary (multi-currency incl. Indian
grouping and `k` shorthand), years, seniority and employment type.  Every
function returns explicit Nones on no evidence — never fabricated values.
"""

from __future__ import annotations

import re

from app.models.enums import EmploymentType, ExperienceLevel
from app.services.resume_parser import _SENIORITY_MAP, _infer_seniority

_CURRENCY_SIGNS: dict[str, str] = {
    "$": "USD",
    "usd": "USD",
    "₹": "INR",
    "inr": "INR",
    "€": "EUR",
    "eur": "EUR",
    "£": "GBP",
    "gbp": "GBP",
    "a$": "AUD",
    "aud": "AUD",
    "c$": "CAD",
    "cad": "CAD",
}

_CUR = r"[$₹€£]|usd|inr|eur|gbp|aud|cad"
_NUM = r"\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|\d{4,7}(?:\.\d+)?"
_SALARY_RE = re.compile(
    rf"(?P<cur1>{_CUR})?\s*"
    rf"(?P<a>{_NUM})(?P<k1>[kK])?"
    rf"\s*(?:[-–—]|\bto\b)\s*"
    rf"(?P<cur2>{_CUR})?\s*"
    rf"(?P<b>{_NUM})(?P<k2>[kK])?",
    re.IGNORECASE,
)
# `90k - 130k` shorthand — the standalone short numbers never match _NUM
_SALARY_K_RE = re.compile(
    rf"(?P<cur1>{_CUR})?\s*(?P<a>\d{{1,3}}(?:\.\d+)?)\s*[kK]\s*"
    rf"(?:[-–—]|\bto\b)\s*"
    rf"(?P<cur2>{_CUR})?\s*(?P<b>\d{{1,3}}(?:\.\d+)?)\s*[kK]",
    re.IGNORECASE,
)
_SALARY_SIGNAL_RE = re.compile(r"salary|compensation|\bpay\b|\bctc\b|stipend|[$₹€£]|\brs\b|\b$rs\b|\busd\b|\beur\b|\bgbp\b", re.IGNORECASE)
_YEARS_EXP_RE = re.compile(r"(\d+)\+?\s*(?:years?|yrs)\s*(?:of\s+)?experience", re.IGNORECASE)
_YEARS_RANGE_RE = re.compile(r"(\d+)\s*(?:[-–—]|to)\s*\d+\s*(?:years?|yrs)", re.IGNORECASE)
_YEARS_SIMPLE_RE = re.compile(r"(\d+)\+?\s*(?:years?|yrs)", re.IGNORECASE)


def _to_int(num: str, k: str | None) -> int:
    value = float(num.replace(",", ""))
    if k:
        value *= 1000
    return int(round(value))


def _detect_currency(window: str, default_currency: str) -> str:
    window = window.lower()
    for sign, code in sorted(_CURRENCY_SIGNS.items(), key=lambda kv: -len(kv[0])):
        if sign in window:
            return code
    return default_currency


def parse_salary(
    text: str, default_currency: str = "USD"
) -> tuple[int | None, int | None, str | None]:
    """Extract (min, max, currency) from salary text; all-None when absent.

    Big-number matches require a currency signal or salary keyword nearby so
    date ranges ("2015 - 2019") and phone codes never become salaries; the
    `90k - 130k` shorthand is its own unambiguous pattern.
    """
    if not text:
        return None, None, None

    km = _SALARY_K_RE.search(text)
    if km:
        low = int(round(float(km.group("a")) * 1000))
        high = int(round(float(km.group("b")) * 1000))
        window = text[max(0, km.start() - 8) : km.end() + 12]
        currency = _detect_currency(window, default_currency)
        if low > high:
            low, high = high, low
        if low > 0:
            return low, high, currency

    m = _SALARY_RE.search(text)
    if not m:
        return None, None, None

    window = text[max(0, m.start() - 40) : m.end() + 20]
    if not _SALARY_SIGNAL_RE.search(window):
        return None, None, None

    low = _to_int(m.group("a"), m.group("k1"))
    high = _to_int(m.group("b"), m.group("k2"))
    currency = _detect_currency(window, default_currency)
    if low > high:
        low, high = high, low
    if low <= 0:
        return None, None, None
    return low, high, currency


def parse_location(raw: str | None) -> str | None:
    """Normalise a location string; 'Remote' when that is all we know."""
    if not raw:
        return None
    cleaned = re.sub(r"\s+", " ", str(raw)).strip(" ,;")
    if not cleaned:
        return None
    return cleaned[:150]


def parse_years(text: str) -> float | None:
    """'3+ years of experience' → 3.0; '5-7 years' → 5.0 (band floor)."""
    if not text:
        return None
    for pattern in (_YEARS_EXP_RE, _YEARS_RANGE_RE, _YEARS_SIMPLE_RE):
        m = pattern.search(text)
        if m:
            return float(m.group(1))
    return None


# Postings that say they want freshers / 0-1 years. Indian listings use "fresher"
# far more than "entry level", and it usually appears in the description only.
_FRESHER_RE = re.compile(
    r"\bfreshers?\b"
    r"|\b0\s*(?:[-–—]|to)\s*[12]\s*(?:\+\s*)?(?:years?|yrs)\b"
    r"|\bentry[\s-]+level\b"
    r"|\bno\s+(?:prior\s+|previous\s+)?(?:work\s+)?experience\s+(?:is\s+)?(?:required|needed|necessary)\b"
    r"|\bgraduate\s+(?:trainee|engineer\s+trainee|program(?:me)?)\b"
    r"|\bcampus\s+(?:hire|hiring|recruitment|drive|placement)\b"
    r"|\b(?:recent|new|fresh)\s+grad(?:uate)?s?\b",
    re.IGNORECASE,
)
_ENTRY_TITLE_RE = re.compile(
    r"\b(?:intern|internship|trainee|apprentice|junior|jr\.?|graduate|fresher|freshers|entry[\s-]+level)\b",
    re.IGNORECASE,
)
_SENIOR_TITLE_RE = re.compile(
    r"\b(?:senior|sr\.?|lead|principal|staff|architect|manager|director|head|vp|vice\s+president|chief|cto|ceo|coo)\b",
    re.IGNORECASE,
)


def detect_fresher(text: str | None) -> bool:
    """True when a posting/query explicitly targets freshers / 0-1 years / entry level."""
    return bool(text and _FRESHER_RE.search(text))


def map_seniority(
    title: str, years: float | None = None, description: str | None = None
) -> ExperienceLevel:
    """Posting → experience level.

    Order (first match wins):
      1. entry words in the title (intern, trainee, junior, fresher, ...) unless
         the title is also senior ("Senior Trainer" stays senior)
      2. senior/lead/executive words in the title → the resume seniority ladder
      3. the description explicitly asks for freshers / 0-1 years / entry level
      4. the required years parsed from the posting (0-1 → entry, 2-4 → mid, ...)
      5. ladder default for generic titles ("developer", "engineer") → mid

    Previously a generic title word ("developer") decided "mid" before the
    years or the description were looked at, so "Full Stack Developer (0-1
    years, freshers welcome)" was labelled mid; and the ladder mapped the word
    "entry" itself to mid.
    """
    t = title or ""
    senior_title = bool(_SENIOR_TITLE_RE.search(t))
    if _ENTRY_TITLE_RE.search(t) and not senior_title:
        return ExperienceLevel.ENTRY
    if not senior_title:
        if detect_fresher(description):
            return ExperienceLevel.ENTRY
        if years is not None:
            if years < 2:
                return ExperienceLevel.ENTRY
            if years < 5:
                return ExperienceLevel.MID
            if years < 8:
                return ExperienceLevel.SENIOR
            if years < 12:
                return ExperienceLevel.LEAD
            return ExperienceLevel.EXECUTIVE
    level = _infer_seniority(t, years)  # type: ignore[arg-type]
    if level in {e.value for e in ExperienceLevel}:
        return ExperienceLevel(level)
    if years is not None:
        if years < 2:
            return ExperienceLevel.ENTRY
        if years < 5:
            return ExperienceLevel.MID
        if years < 8:
            return ExperienceLevel.SENIOR
        if years < 12:
            return ExperienceLevel.LEAD
        return ExperienceLevel.EXECUTIVE
    return ExperienceLevel.MID


def detect_employment_type(text: str) -> EmploymentType:
    lowered = (text or "").lower()
    if "internship" in lowered or "intern" in lowered:
        return EmploymentType.INTERNSHIP
    if "part-time" in lowered or "part time" in lowered:
        return EmploymentType.PART_TIME
    if "contract" in lowered:
        return EmploymentType.CONTRACT
    if "temporary" in lowered or "temp " in lowered:
        return EmploymentType.TEMPORARY
    return EmploymentType.FULL_TIME


def detect_remote(title: str, description: str, location: str | None) -> bool:
    haystack = f"{title} {description} {location or ''}".lower()
    return bool(re.search(r"\bremote\b|work from home|wfh\b", haystack))


# Re-exported for callers that only import from ingest.parse
__all__ = [
    "detect_employment_type",
    "detect_remote",
    "map_seniority",
    "parse_location",
    "parse_salary",
    "parse_years",
    "_SENIORITY_MAP",
]
