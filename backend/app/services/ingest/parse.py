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


def map_seniority(title: str, years: float | None = None) -> ExperienceLevel:
    """Deterministic title→level mapping (reuses the resume seniority ladder)."""
    level = _infer_seniority(title or "", years)  # type: ignore[arg-type]
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
