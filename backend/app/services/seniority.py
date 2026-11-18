"""Seniority: classify job postings, and detect seniority intent in queries.

Why this exists: job seniority used to come from the *resume* keyword ladder,
where "developer" / "software engineer" / "analyst" mean **mid**, and title
words were checked before years of experience.  Nearly every live listing
("Python Developer — freshers welcome, 0–1 years") was therefore labelled
mid, so a fresher search could not tell entry roles from senior ones.

Rules here are deterministic and Indian-market aware ("fresher", "2026
batch", "campus hiring", "0-1 yrs"):

* ``classify_job(title, description)`` → ``LevelGuess(level, explicit, reason)``.
  ``explicit=False`` means "no evidence, defaulted to mid" — search treats
  those as *unknown* rather than as mid.
* ``detect_level_intent(text)`` → the level a search query asks for, or None.
* ``level_tier(guess, wanted)`` → 0 (explicit match), 1 (unknown), 2 (mismatch)
  for ordering/filtering result sets.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.models.enums import ExperienceLevel

E, M, S, L, X = (
    ExperienceLevel.ENTRY,
    ExperienceLevel.MID,
    ExperienceLevel.SENIOR,
    ExperienceLevel.LEAD,
    ExperienceLevel.EXECUTIVE,
)

# Title signals, strongest first.  Word-bounded; checked on the title only.
_TITLE_RULES: list[tuple[re.Pattern[str], ExperienceLevel]] = [
    (re.compile(r"\b(chief|cto|ceo|coo|cfo|vp|vice president|director|head of)\b", re.I), X),
    (re.compile(r"\b(principal|staff|lead|architect|engineering manager|manager)\b", re.I), L),
    (re.compile(r"\b(senior|sr\.?|snr)\b", re.I), S),
    (re.compile(
        r"\b(intern(ship)?|trainee|apprentice|fresher|freshers|graduate|grad|junior|jr\.?|entry[- ]level|"
        r"associate (software|developer|engineer|analyst|consultant)|campus|new grad)\b",
        re.I,
    ), E),
    (re.compile(r"\b(mid[- ]level|intermediate)\b", re.I), M),
]

# Description signals for entry level (Indian + global phrasing).
_ENTRY_TEXT = re.compile(
    r"\b(freshers?(\s+(can|may)\s+apply|\s+welcome|\s+only)?|"
    r"(19|20)\d\d\s*(/\s*(19|20)?\d\d\s*)?(pass[- ]?outs?|batch|graduates?)|"
    r"recent (graduate|grad)s?|new grads?|campus (hiring|drive|placement)|"
    r"no (prior )?experience (is )?(required|needed)|entry[- ]level|"
    r"0\s*(-|–|to)\s*[12]\s*(years?|yrs))\b",
    re.I,
)

_YEARS_NUM = re.compile(r"(\d{1,2})\s*(?:\+|plus)?\s*(?:(?:-|–|to)\s*\d{1,2}\s*)?(?:years?|yrs)\b", re.I)
_EXPERIENCE_WORD = re.compile(r"\b(experience|exp)\b", re.I)


@dataclass(frozen=True)
class LevelGuess:
    level: ExperienceLevel
    explicit: bool
    reason: str


def _years_floor(text: str) -> int | None:
    """Smallest required-years figure stated with 'experience'."""
    text = text or ""
    found = []
    for m in _YEARS_NUM.finditer(text):
        # "experience" within ~40 chars either side ("5+ years of hands-on
        # experience", "Experience: 0 to 2 years") — not "founded 10 years ago"
        window = text[max(0, m.start() - 40) : m.end() + 40]
        if _EXPERIENCE_WORD.search(window):
            found.append(int(m.group(1)))
    found = [y for y in found if y <= 30]
    return min(found) if found else None


def _level_for_years(years: int) -> ExperienceLevel:
    if years < 2:
        return E
    if years < 5:
        return M
    if years < 8:
        return S
    return L


def classify_job(title: str, description: str | None = None) -> LevelGuess:
    """Seniority of one posting with an explicit/defaulted flag and a reason."""
    title = title or ""
    for pattern, level in _TITLE_RULES:
        m = pattern.search(title)
        if m:
            return LevelGuess(level, True, f"title says '{m.group(0)}'")

    text = description or ""
    years = _years_floor(text)
    if _ENTRY_TEXT.search(text) and (years is None or years < 2):
        m = _ENTRY_TEXT.search(text)
        return LevelGuess(E, True, f"posting says '{m.group(0).strip()}'")  # type: ignore[union-attr]
    if years is not None:
        return LevelGuess(_level_for_years(years), True, f"{years}+ years of experience required")
    return LevelGuess(M, False, "no seniority signal (defaulted)")


# ---------------------------------------------------------------------------
# Query intent
# ---------------------------------------------------------------------------

_INTENT_RULES: list[tuple[re.Pattern[str], ExperienceLevel]] = [
    (re.compile(
        r"\b(freshers?|fresh graduates?|graduates?|new grads?|entry[- ]level|junior|jr|trainee|"
        r"no experience|0\s*(-|–|to)?\s*[12]?\s*(years?|yrs)|(19|20)\d\d\s*(batch|pass[- ]?outs?)|"
        r"campus|beginner|first job|starting out|college students?|just graduated)\b",
        re.I,
    ), E),
    (re.compile(r"\b(senior|sr|experienced)\b", re.I), S),
    (re.compile(r"\b(lead|principal|staff)\b", re.I), L),
    (re.compile(r"\b(director|vp|head of|cto|executive)\b", re.I), X),
    (re.compile(r"\b(mid[- ]level|intermediate)\b", re.I), M),
]

# Words that carry seniority intent but would hurt keyword matching if kept
# in a full-text / provider query ("jobs for freshers" ≠ a skill).
INTENT_STOPWORDS = re.compile(
    r"\b(freshers?|fresh graduates?|new grads?|entry[- ]level|(19|20)\d\d\s*(batch|pass[- ]?outs?)|"
    r"for beginners?|no experience|first job)\b",
    re.I,
)


def detect_level_intent(text: str | None) -> ExperienceLevel | None:
    """Seniority a free-text query asks for ("fresher python jobs" → ENTRY)."""
    if not text:
        return None
    for pattern, level in _INTENT_RULES:
        if pattern.search(text):
            return level
    return None


def strip_intent_words(text: str) -> str:
    """Remove seniority-only words from a keyword query; keep the rest."""
    cleaned = INTENT_STOPWORDS.sub(" ", text or "")
    return " ".join(cleaned.split())


def level_tier(level: ExperienceLevel | None, explicit: bool, wanted: ExperienceLevel) -> int:
    """0 = explicit match, 1 = unknown (no evidence), 2 = explicit mismatch.

    For ENTRY requests, an explicit *mid* posting with no years stated is
    still "unknown-ish" only if it was defaulted — explicit mid stays 2.
    """
    if level is None or not explicit:
        return 1
    return 0 if level == wanted else 2
