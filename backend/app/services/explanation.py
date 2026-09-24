"""Explanation contract builder (plan §12).

Every recommendation carries a structured explanation whose numbers are taken
verbatim from the deterministic scorer — components feed the contract, the
contract feeds the UI.  A validator asserts internal consistency (contributions
sum to the final score) so no layer can drift.

Text templates are deterministic here; optional LLM polish (Phase 2, §15) may
rewrite `summary` only, never the numbers.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.config import get_settings
from app.services.scoring import ScoreResult


@dataclass
class ExplanationContract:
    summary: str
    components: dict[str, float]                 # verbatim from ScoreResult
    contributions: dict[str, float]               # weighted points
    strengths: list[str] = field(default_factory=list)
    concerns: list[str] = field(default_factory=list)
    recommended_action: str = ""
    delta_note: str | None = None                # LTR blend delta (null in deterministic)

    def as_dict(self) -> dict:
        return {
            "summary": self.summary,
            "components": dict(self.components),
            "contributions": dict(self.contributions),
            "strengths": list(self.strengths),
            "concerns": list(self.concerns),
            "recommended_action": self.recommended_action,
            "delta_note": self.delta_note,
        }


def _band(score: float) -> str:
    if score >= 85:
        return "excellent"
    if score >= 70:
        return "strong"
    if score >= 50:
        return "moderate"
    return "limited"


def build_explanation(
    job_title: str,
    company_name: str | None,
    result: ScoreResult,
    *,
    family: str | None = None,
    display_score: float | None = None,
) -> ExplanationContract:
    """Build the §12 contract from a ScoreResult — numbers verbatim, no recomputation.

    `display_score` is the score actually shown to the user (may differ from
    `result.final` under ltr_blend — the difference is explained by
    `delta_note`).  Components/contributions always stay verbatim from the
    deterministic scorer.
    """
    display = result.final if display_score is None else display_score
    comp = result.components
    strengths: list[str] = []
    concerns: list[str] = []
    detail = result.skill_detail

    # Strengths from component rules (§12 mapping)
    if detail.matched:
        top = ", ".join(detail.matched[:3])
        strengths.append(f"Skills overlap: {top}")
    if detail.transferable:
        strengths.append(
            "Transferable background: " + ", ".join(detail.transferable[:3])
        )
    if comp.get("project", 0) >= 70:
        strengths.append("Your projects evidence the technologies this role uses")
    if comp.get("location", 0) >= 80:
        strengths.append("Location fit is a plus" if comp.get("location", 0) < 100
                         else "Location/remote arrangement matches your preferences")
    if comp.get("experience", 0) >= 85:
        strengths.append("Your experience level aligns well with this role")
    if comp.get("education", 0) >= 85:
        strengths.append("Education requirements are satisfied")
    if comp.get("semantic", 0) >= 70:
        strengths.append("Your background reads as closely related to this posting")

    # Concerns
    if detail.missing_required:
        concerns.append(
            "Missing required skills: " + ", ".join(detail.missing_required[:3])
        )
    if comp.get("project", 0) <= 40:
        concerns.append("No projects yet evidence the required stack")
    if comp.get("experience", 0) < 60:
        concerns.append("Experience level is below what this posting asks for")
    if comp.get("salary", 0) < 50:
        concerns.append("Salary band may be below your expectation")
    if comp.get("location", 0) <= 40:
        concerns.append("Location does not match your preferences and the role is not remote")

    # Recommended action: deterministic, prioritises the first missing required skill
    if detail.missing_required:
        first = detail.missing_required[0]
        recommended_action = (
            f"Build one small project using {first} and add it to your profile — "
            f"that converts your biggest gap into demonstrated evidence."
        )
    elif comp.get("project", 0) <= 40:
        recommended_action = (
            "Add a project that uses your existing skills in production form "
            "(deployed, linked) to raise the project component."
        )
    else:
        recommended_action = "Apply — this posting aligns with your current profile."

    who = company_name or "this company"
    summary = (
        f"{job_title} at {who} is a {_band(display)} match "
        f"({display:.1f}%)"
        + (f" for a {family} direction" if family else "")
        + "."
    )

    return ExplanationContract(
        summary=summary,
        components=dict(comp),
        contributions=dict(result.contributions),
        strengths=strengths,
        concerns=concerns,
        recommended_action=recommended_action,
        delta_note=None,
    )


def readiness_from_score(score: float) -> dict:
    """Readiness value/band for a displayed score (plan §12, §6 M3).

    Two paths, one output shape — ``{value: 0..1, band}``:

    * **Calibrated (M3):** when the calibrator artifact is active, value is
      the isotonic/Platt P(positive outcome) for this score, banded by
      settings (default low <0.60 ≤ medium <0.80 ≤ high).  The calibrator is
      monotone non-decreasing, so roadmap/simulator score orderings survive
      the mapping.
    * **Raw fallback:** Phase-1 mapping — value = score/100 with bands
      low <0.50 ≤ medium <0.75 ≤ high (no artifact, or
      ``readiness_calibrator_enabled=false``).
    """
    from app.services.calibration import predict_positive  # noqa: PLC0415

    settings = get_settings()
    calibrated = predict_positive(float(score))
    if calibrated is not None:
        value = round(max(0.0, min(1.0, calibrated)), 2)
        if value >= settings.readiness_band_high:
            band = "high"
        elif value >= settings.readiness_band_medium:
            band = "medium"
        else:
            band = "low"
        return {"value": value, "band": band}

    value = round(max(0.0, min(100.0, float(score))) / 100.0, 2)
    if value >= 0.75:
        band = "high"
    elif value >= 0.50:
        band = "medium"
    else:
        band = "low"
    return {"value": value, "band": band}


def validate_explanation(contract: ExplanationContract, expected_final: float, tol: float = 0.15) -> list[str]:
    """Return a list of consistency violations (empty = valid).

    Checks: contributions sum to expected_final, components within [0,100],
    and component keys match contribution keys.
    """
    problems: list[str] = []
    total = sum(contract.contributions.values())
    if abs(total - expected_final) > tol:
        problems.append(
            f"contributions sum {total:.2f} != final score {expected_final:.2f} (tol {tol})"
        )
    for name, value in contract.components.items():
        if not (0.0 <= value <= 100.0):
            problems.append(f"component {name}={value} outside [0,100]")
    if set(contract.components) != set(contract.contributions):
        problems.append("component keys != contribution keys")
    if not contract.strengths and not contract.concerns:
        problems.append("explanation has neither strengths nor concerns")
    if not contract.recommended_action:
        problems.append("recommended_action is empty")
    return problems
