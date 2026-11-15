"""LLM-assisted curation helpers (P3, P10) with deterministic fallbacks."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


def propose_skill_aliases(raw_skills: list[str]) -> list[dict[str, Any]]:
    """P3: propose canonical mappings/aliases for raw skill strings."""
    cleaned = [str(s).strip() for s in raw_skills if str(s).strip()]
    if not cleaned:
        return []
    try:
        from app.services.llm import get_provider, mark_flagged, prompts, validators

        provider = get_provider()
        if provider is None:
            return [{"raw": s, "canonical": s, "alias_of": None, "confidence": 0.0, "source": "deterministic"} for s in cleaned]

        class _Proposal(BaseModel):
            raw: str
            canonical: str
            alias_of: str | None = None
            confidence: float = 0.0

        class _Out(BaseModel):
            proposals: list[_Proposal] = []

        out, usage = provider.complete_json(
            _Out,
            prompts.p3_skill_proposal(cleaned),
            system="Map raw skills to canonical names conservatively.",
            max_tokens=1200,
            route="P3",
        )
        proposals = []
        for p in out.proposals:
            probs = validators.validate_skill_tokens([p.canonical], " ".join(cleaned), extra_allowed=[p.raw])
            if probs:
                continue
            proposals.append({"raw": p.raw, "canonical": p.canonical, "alias_of": p.alias_of, "confidence": float(p.confidence), "source": provider.name})
        if not proposals:
            mark_flagged(usage, "no valid P3 proposals")
            return [{"raw": s, "canonical": s, "alias_of": None, "confidence": 0.0, "source": "deterministic"} for s in cleaned]
        return proposals
    except Exception:
        return [{"raw": s, "canonical": s, "alias_of": None, "confidence": 0.0, "source": "deterministic"} for s in cleaned]


def propose_skill_edges(src: str, dst: str, context: str = "") -> list[dict[str, Any]]:
    """P10: propose prerequisite/transfer edges for admin review (never auto-approved)."""
    src = (src or "").strip()
    dst = (dst or "").strip()
    if not src or not dst or src.lower() == dst.lower():
        return []
    try:
        from app.services.llm import get_provider, mark_flagged, prompts

        provider = get_provider()
        if provider is None:
            return []

        class _Edge(BaseModel):
            from_: str | None = None
            to: str | None = None
            type: str = "prereq"
            weight: float = 0.5
            confidence: float = 0.0
            rationale: str = ""

            class Config:
                populate_by_name = True
                fields = {"from_": {"alias": "from"}}

        class _Out(BaseModel):
            proposals: list[dict[str, Any]] = []

        out, usage = provider.complete_json(
            _Out,
            prompts.p10_edge_proposal(src, dst, context=context),
            system="Propose only high-confidence skill graph edges.",
            max_tokens=600,
            route="P10",
        )
        valid = []
        for p in out.proposals:
            frm = str(p.get("from") or src).strip().lower()
            to = str(p.get("to") or dst).strip().lower()
            etype = str(p.get("type") or "prereq").strip().lower()
            if frm == to or not frm or not to:
                continue
            if etype not in {"prereq", "transfer", "supersedes"}:
                continue
            conf = float(p.get("confidence") or 0.0)
            if conf < 0.8:
                continue
            valid.append({
                "from": frm,
                "to": to,
                "type": etype,
                "weight": max(0.0, min(1.0, float(p.get("weight") or 0.5))),
                "confidence": conf,
                "rationale": str(p.get("rationale") or ""),
                "approved": False,
                "source": provider.name,
            })
        if not valid:
            mark_flagged(usage, "no valid P10 proposals")
        return valid
    except Exception:
        return []
