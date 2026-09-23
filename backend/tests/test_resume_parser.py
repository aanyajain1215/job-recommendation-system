"""
Unit tests for app.services.resume_parser (regex path only — no external API calls).
Run with: pytest tests/test_resume_parser.py -v
"""
import pytest

from app.services.resume_parser import (
    RegexResumeParser,
    _estimate_years,
    _extract_text,
    _infer_seniority,
    ParsedResume,
)


# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------

class TestExtractText:
    def test_plain_txt(self):
        content = b"Hello, I know Python and Docker."
        result = _extract_text(content, ".txt")
        assert "Python" in result
        assert "Docker" in result

    def test_latin1_fallback(self):
        content = "Café résumé".encode("latin-1")
        result = _extract_text(content, ".txt")
        assert len(result) > 0

    def test_unknown_extension_treated_as_text(self):
        result = _extract_text(b"plain content", ".xyz")
        assert result == "plain content"


# ---------------------------------------------------------------------------
# Year estimation
# ---------------------------------------------------------------------------

class TestEstimateYears:
    def test_simple_year_range(self):
        text = "Software Engineer at Acme 2019 - 2022"
        years = _estimate_years(text)
        assert years == 3.0

    def test_present_keyword(self):
        text = "Senior Dev 2020 – Present"
        years = _estimate_years(text)
        import datetime
        current = datetime.datetime.now().year
        expected = float(current - 2020)
        assert years == expected

    def test_no_dates_returns_none(self):
        text = "I am a Python developer with great skills."
        assert _estimate_years(text) is None

    def test_multiple_ranges_summed(self):
        text = "Intern 2015-2016\nEngineer 2017-2020"
        years = _estimate_years(text)
        assert years == 4.0


# ---------------------------------------------------------------------------
# Seniority inference
# ---------------------------------------------------------------------------

class TestInferSeniority:
    def test_senior_keyword(self):
        assert _infer_seniority("Senior Software Engineer at Google", None) == "senior"

    def test_intern_keyword(self):
        assert _infer_seniority("Software Intern at startup", None) == "entry"

    def test_fallback_to_years_junior(self):
        assert _infer_seniority("I build stuff", 1.0) == "entry"

    def test_fallback_to_years_senior(self):
        assert _infer_seniority("I build stuff", 6.0) == "senior"

    def test_no_signal_returns_none(self):
        assert _infer_seniority("", None) is None


# ---------------------------------------------------------------------------
# RegexResumeParser full pipeline
# ---------------------------------------------------------------------------

SAMPLE_RESUME = """
John Doe
Senior Software Engineer

EXPERIENCE
Google — Senior Backend Engineer
2018 - 2022
Built scalable APIs using Python, FastAPI, PostgreSQL, Docker, and Redis.
Led a team of 5 engineers.

Amazon — Software Engineer
2016 - 2018
Worked on distributed systems using Java and Kafka.

SKILLS
Python, FastAPI, PostgreSQL, Docker, Redis, Java, Kafka, AWS, Git

EDUCATION
B.Tech Computer Science, IIT Bombay, 2016
"""


class TestRegexResumeParser:
    def setup_method(self):
        self.parser = RegexResumeParser()

    def test_skills_extracted(self):
        result = self.parser.parse(SAMPLE_RESUME)
        skill_names = {s.name for s in result.skills}
        assert "Python" in skill_names
        assert "Docker" in skill_names
        assert "PostgreSQL" in skill_names

    def test_years_estimated(self):
        result = self.parser.parse(SAMPLE_RESUME)
        # 2018-2022 = 4, 2016-2018 = 2 → 6 total
        assert result.years_of_experience is not None
        assert result.years_of_experience >= 4.0

    def test_seniority_detected(self):
        result = self.parser.parse(SAMPLE_RESUME)
        assert result.seniority == "senior"

    def test_parser_used_tag(self):
        result = self.parser.parse(SAMPLE_RESUME)
        assert result.parser_used == "regex"

    def test_raw_text_preserved(self):
        result = self.parser.parse(SAMPLE_RESUME)
        assert "Google" in result.raw_text

    def test_empty_text_returns_empty_result(self):
        result = self.parser.parse("")
        assert result.skills == []
        assert result.years_of_experience is None

    def test_parsed_resume_is_pydantic_model(self):
        result = self.parser.parse(SAMPLE_RESUME)
        assert isinstance(result, ParsedResume)
        # Serializable to dict
        d = result.model_dump()
        assert "skills" in d
        assert "years_of_experience" in d
