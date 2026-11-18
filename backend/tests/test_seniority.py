"""Seniority classification + fresher intent (regression: fresher searches
returned senior roles because postings were labelled with the resume ladder)."""

import pytest

from app.models.enums import ExperienceLevel as L
from app.services.seniority import classify_job, detect_level_intent, level_tier, strip_intent_words


@pytest.mark.parametrize(
    "title,desc,level,explicit",
    [
        ("Python Developer", "Freshers can apply. Good communication.", L.ENTRY, True),
        ("Python Developer", "We need 0-1 years experience in Django", L.ENTRY, True),
        ("Software Engineer", "2025/2026 batch graduates welcome", L.ENTRY, True),
        ("Data Analyst", "Experience: 0 to 2 years", L.ENTRY, True),
        ("Graduate Engineer Trainee", "", L.ENTRY, True),
        ("Python Developer", "Minimum 3 years of experience with Python", L.MID, True),
        ("Python Developer", "Requires 5+ years of hands-on experience", L.SENIOR, True),
        ("Senior Python Developer", "Freshers welcome", L.SENIOR, True),   # title wins
        ("Tech Lead - Backend", "", L.LEAD, True),
        ("Python Developer", "We were founded 10 years ago. Build APIs.", L.MID, False),
        ("Major Account Executive", "Sell to public sector.", L.MID, False),  # sales title, not exec level
    ],
)
def test_classify_job(title, desc, level, explicit):
    g = classify_job(title, desc)
    assert (g.level, g.explicit) == (level, explicit), g.reason


@pytest.mark.parametrize(
    "q,level",
    [
        ("fresher python jobs", L.ENTRY),
        ("jobs for freshers 2026 batch", L.ENTRY),
        ("entry level data analyst", L.ENTRY),
        ("I just graduated, need my first job", L.ENTRY),
        ("senior react developer", L.SENIOR),
        ("python developer pune", None),
    ],
)
def test_detect_level_intent(q, level):
    assert detect_level_intent(q) == level


def test_strip_intent_words_keeps_role():
    assert strip_intent_words("fresher python developer jobs") == "python developer jobs"
    assert strip_intent_words("jobs for freshers 2026 batch") == "jobs for"


def test_level_tier():
    assert level_tier(L.ENTRY, True, L.ENTRY) == 0
    assert level_tier(L.MID, False, L.ENTRY) == 1
    assert level_tier(L.SENIOR, True, L.ENTRY) == 2
