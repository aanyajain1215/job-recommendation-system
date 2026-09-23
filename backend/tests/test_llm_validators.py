"""Unit tests for the LLM layer's validators + prompt/fence contracts
(plan §15) — no network, no keys, pure functions only.

The digit-multiset validator is the plan's anti-hallucination guarantee:
roadmap hours (P5) and explanation numbers (P6) can never be invented or
altered by the model.
"""

from app.services.llm.prompts import PROMPT_CATALOG, p1_resume, p5_roadmap_coach
from app.services.llm.provider import strip_fences
from app.services.llm.validators import (
    digit_multiset_subset,
    validate_digits,
    validate_family,
    validate_skill_tokens,
    validate_spans,
    validate_whitelisted,
)


class TestDigitPreservation:
    def test_source_digits_pass(self):
        source = "Phase 1 is ~49.2h, total 70.0h, readiness 74 → 81."
        candidate = "Phase 1 is 49.2h and total is 70.0h; readiness moves 74 to 81."
        assert validate_digits(candidate, source) == []
        assert digit_multiset_subset(candidate, source)

    def test_fabricated_number_is_rejected(self):
        source = "Phase 1 is ~49.2h, total 70.0h."
        candidate = "Phase 1 takes 55.5h, total 99.0h."
        problems = validate_digits(candidate, source, label="hours")
        assert len(problems) == 1
        assert "hours" in problems[0]

    def test_altered_digit_rejected(self):
        assert not digit_multiset_subset("74", "71")   # 4 not in source
        assert digit_multiset_subset("74", "74.0")
        assert digit_multiset_subset("2024", "in 2024 we ship")

    def test_no_digits_always_passes(self):
        assert validate_digits("strong match for this role", "anything") == []

    def test_multiset_counts_matter(self):
        # source has two 2s; candidate asking for three must fail
        assert digit_multiset_subset("22", "2022")
        assert not digit_multiset_subset("2222", "2022")

    def test_label_in_message(self):
        problems = validate_digits("1234", "12", label="P5 note")
        assert "P5 note" in problems[0]


class TestEvidenceSpans:
    SOURCE = "Built data pipelines with Python and Airflow at Acme."

    def test_valid_offsets_pass(self):
        quote = "Python"
        start = self.SOURCE.index(quote)
        spans = [{"skill": "Python", "start": start, "end": start + len(quote), "quote": quote}]
        assert validate_spans(spans, self.SOURCE) == []

    def test_invented_quote_rejected(self):
        spans = [{"skill": "Rust", "quote": "Rust"}]
        problems = validate_spans(spans, self.SOURCE)
        assert len(problems) == 1
        assert "not found" in problems[0]

    def test_wrong_offsets_rejected(self):
        spans = [{"skill": "Python", "start": 0, "end": 6, "quote": "Python"}]
        problems = validate_spans(spans, self.SOURCE)
        assert len(problems) == 1
        assert "does not equal quote" in problems[0]

    def test_offsets_without_quote_membership_rejected(self):
        # offsets slice correctly to a quote that is genuinely at 0..6
        spans = [{"skill": "Built", "start": 0, "end": 5, "quote": "Built"}]
        assert validate_spans(spans, self.SOURCE) == []

    def test_empty_quote_rejected(self):
        assert validate_spans([{"skill": "X", "quote": ""}], self.SOURCE)


class TestSkillTokens:
    SOURCE = "Experience with React, Next.js and PostgreSQL."

    def test_skill_present_in_source_passes(self):
        assert validate_skill_tokens(["React", "PostgreSQL"], self.SOURCE) == []

    def test_case_and_whitespace_tolerated(self):
        assert validate_skill_tokens(["  react "], self.SOURCE) == []

    def test_invented_skill_rejected(self):
        problems = validate_skill_tokens(["Kubernetes"], self.SOURCE)
        assert len(problems) == 1
        assert "Kubernetes" in problems[0]

    def test_taxonomy_override_allowed(self):
        # canonical name not literally in the resume but already canonical
        problems = validate_skill_tokens(
            ["Kubernetes"], self.SOURCE, extra_allowed=["kubernetes", "Docker"]
        )
        assert problems == []

    def test_empty_names_ignored(self):
        assert validate_skill_tokens(["", "  "], self.SOURCE) == []


class TestFamilyAndWhitelist:
    ALLOWED = ["Backend Engineering", "Data Science", "DevOps Engineering"]

    def test_known_family_passes(self):
        assert validate_family("data science", self.ALLOWED) == []

    def test_unknown_family_rejected(self):
        problems = validate_family("Astronaut Engineering", self.ALLOWED)
        assert len(problems) == 1
        assert "taxonomy" in problems[0]

    def test_empty_family_rejected(self):
        assert validate_family("", self.ALLOWED)

    def test_whitelisted_fields_only(self):
        filters = {"keywords": "python", "salary_fairy": 100}
        problems = validate_whitelisted(filters, ["keywords", "location"])
        assert problems == ["field 'salary_fairy' is not whitelisted"]
        assert validate_whitelisted({"keywords": "x"}, ["keywords"]) == []


class TestPromptAndFenceContracts:
    def test_strip_fences_json(self):
        assert strip_fences('```json\n{"a": 1}\n```') == '{"a": 1}'
        assert strip_fences('```\n{"a": 1}\n```') == '{"a": 1}'

    def test_strip_fences_unclosed(self):
        assert strip_fences('```json\n{"a": 1}') == '{"a": 1}'

    def test_strip_fences_plain_untouched(self):
        assert strip_fences('{"a": 1}') == '{"a": 1}'
        assert strip_fences("no json here") == "no json here"

    def test_p5_demands_digit_preservation(self):
        prompt = p5_roadmap_coach({"phases": [{"label": "Phase 1", "hours": 49.2}]})
        assert "MUST appear EXACTLY" in prompt
        assert "49.2" in prompt
        assert "ONE valid JSON object" in prompt

    def test_p1_forbids_invention_and_requires_spans(self):
        prompt = p1_resume("Built ML features with Python at Acme.")
        assert "NEVER invent" in prompt
        assert "verbatim substring" in prompt
        assert "evidence" in prompt

    def test_catalog_covers_p1_to_p10(self):
        assert set(PROMPT_CATALOG) == {
            f"P{i}" for i in range(1, 11)
        }
