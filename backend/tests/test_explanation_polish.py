"""P6 explanation polish — flag-gated, digit-multiset validator (plan §15).

The deterministic template always ships. Polish replaces prose only when
every number survives verbatim; invented/dropped digits, provider errors,
and the default-off flag all fall back to the template. The LLM never
touches components/contributions (§7). No DB required.
"""

from __future__ import annotations

import pytest

from app.services import explanation
from app.services.explanation import build_explanation, validate_explanation
from app.services.scoring import ScoreResult, SkillMatchDetail, combine

GOLDEN = {
    "semantic": 70.0,
    "skill": 68.0,
    "experience": 85.0,
    "education": 100.0,
    "project": 50.0,
    "location": 80.0,
    "salary": 60.0,
    "interest": 75.0,
}

GOOD = {
    "sentences": [
        "ML Engineer at Acme Labs is a strong match (74.0%) for the "
        "Data Science direction."
    ],
    "recommended_action": (
        "Add one small Kubernetes project to your profile to close the "
        "largest gap."
    ),
}
INVENTED_NUMBER = {
    "sentences": ["ML Engineer at Acme Labs is the 99.9% best match."],
    "recommended_action": "Apply today to all similar roles.",
}
DROPPED_NUMBER = {
    "sentences": ["ML Engineer at Acme Labs is a strong match."],
    "recommended_action": "Apply today to all similar roles.",
}


def _result() -> ScoreResult:
    final, contributions = combine(GOLDEN)
    return ScoreResult(
        final=final,
        components=dict(GOLDEN),
        contributions=contributions,
        skill_detail=SkillMatchDetail(
            score=68.0,
            matched=["Python", "FastAPI"],
            missing_required=["Kubernetes"],
            reasons=["Matches 2 relevant skills: Python, FastAPI"],
        ),
    )


def _enable_flag(monkeypatch) -> None:
    real = explanation.get_settings()
    monkeypatch.setattr(
        explanation,
        "get_settings",
        lambda: real.model_copy(update={"explain_llm": True}),
    )


def _install_provider(monkeypatch, payload=None, *, error: bool = False) -> None:
    class Fake:
        def complete_json(self, schema, prompt, *, route=None, **_kwargs):
            assert route == "explain_polish"
            if error:
                raise RuntimeError("llm down")
            return schema.model_validate(payload), None

    import app.services.llm.provider as provider_mod

    monkeypatch.setattr(provider_mod, "get_provider", lambda: Fake())
    monkeypatch.setattr(provider_mod, "llm_available", lambda: True)


def _build():
    return build_explanation("ML Engineer", "Acme Labs", _result(), family="Data Science")


def test_flag_off_keeps_template_and_never_calls_provider(monkeypatch):
    def _boom(*_args, **_kwargs):
        raise AssertionError("provider must not be called when flag is off")

    import app.services.llm.provider as provider_mod

    monkeypatch.setattr(provider_mod, "get_provider", _boom)
    monkeypatch.setattr(provider_mod, "llm_available", lambda: True)

    contract = _build()
    assert "74.0%" in contract.summary
    assert "ML Engineer at Acme Labs" in contract.summary


def test_valid_polish_replaces_prose_keeps_numbers(monkeypatch):
    _enable_flag(monkeypatch)
    _install_provider(monkeypatch, GOOD)

    contract = _build()
    assert contract.summary == GOOD["sentences"][0]
    assert contract.recommended_action == GOOD["recommended_action"]
    assert "74.0%" in contract.summary                    # number verbatim
    assert contract.components == _result().components     # §7: untouched
    assert validate_explanation(contract, _result().final) == []


def test_invented_number_is_discarded(monkeypatch):
    _enable_flag(monkeypatch)
    _install_provider(monkeypatch, INVENTED_NUMBER)

    contract = _build()
    assert "ML Engineer at Acme Labs is a strong match" in contract.summary
    assert "99.9" not in contract.summary


def test_dropped_number_is_discarded(monkeypatch):
    _enable_flag(monkeypatch)
    _install_provider(monkeypatch, DROPPED_NUMBER)

    contract = _build()
    assert "74.0%" in contract.summary                    # template retained


def test_provider_error_falls_back_to_template(monkeypatch):
    _enable_flag(monkeypatch)
    _install_provider(monkeypatch, error=True)

    contract = _build()
    assert "74.0%" in contract.summary
    assert "Kubernetes" in contract.recommended_action


def test_empty_payload_falls_back_to_template(monkeypatch):
    _enable_flag(monkeypatch)
    _install_provider(monkeypatch, {"sentences": [], "recommended_action": ""})

    contract = _build()
    assert "74.0%" in contract.summary


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
