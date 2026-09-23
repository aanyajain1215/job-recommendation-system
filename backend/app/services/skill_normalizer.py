"""Skill name normalisation (plan §20 stage 3 — evidence-preserving).

Cascade (plan §20): exact match → alias table → fuzzy (rapidfuzz ≥ 92)
→ propose as new (returned unmatched so callers can create it).

The DB-agnostic core (`SkillNormalizer`) works on plain lists so it is unit-
testable without a database; `resolve_skill` is the DB-facing convenience
wrapper used by API handlers.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from rapidfuzz import fuzz

from app.models.skill import Skill
from app.models.skill_graph import SkillAlias

log = logging.getLogger(__name__)

FUZZY_THRESHOLD = 92.0
ML_DATA_DIR = Path(__file__).resolve().parents[2] / "ml" / "data"


@dataclass
class NormalizationResult:
    """What happened + the canonical name to persist."""

    canonical: str                 # name to store (original casing if unmatched)
    matched: bool                  # True if mapped to an existing skill
    method: str                    # "exact" | "alias" | "fuzzy" | "new"
    score: float = 100.0           # fuzzy confidence (100 for exact/alias)
    original: str = ""             # raw input, preserved for evidence


def _norm(s: str) -> str:
    return " ".join(s.strip().lower().split())


class SkillNormalizer:
    """Pure normalizer over in-memory canonical names + alias pairs."""

    def __init__(
        self,
        canonical_names: list[str],
        alias_pairs: list[tuple[str, str]] | None = None,
    ) -> None:
        # canonical (as stored) + lookup key
        self._canonical: dict[str, str] = {}
        for name in canonical_names:
            if name:
                self._canonical[_norm(name)] = name
        # alias key -> canonical stored name
        self._aliases: dict[str, str] = {}
        for alias, canonical in alias_pairs or []:
            c = self._canonical.get(_norm(canonical), canonical)
            self._aliases[_norm(alias)] = c
            self._canonical.setdefault(_norm(c), c)

    @classmethod
    def from_yaml(cls) -> "SkillNormalizer":
        """Load curated aliases from ml/data/skill_aliases.yaml (canonicals come from DB)."""
        pairs: list[tuple[str, str]] = []
        path = ML_DATA_DIR / "skill_aliases.yaml"
        if path.exists():
            try:
                import yaml  # noqa: PLC0415

                data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                if isinstance(data, dict):
                    for canonical, aliases in data.items():
                        for alias in aliases or []:
                            pairs.append((str(alias), str(canonical)))
            except Exception:
                log.exception("Failed to load skill_aliases.yaml")
        # canonical_names supplied later via bind(); YAML alone gives aliases
        cls._yaml_pairs = pairs  # type: ignore[attr-defined]
        return cls([], pairs)

    def extend(self, canonical_names: list[str], alias_pairs: list[tuple[str, str]] | None = None) -> None:
        for name in canonical_names:
            if name:
                self._canonical[_norm(name)] = name
        for alias, canonical in alias_pairs or []:
            c = self._canonical.get(_norm(canonical), canonical)
            self._aliases[_norm(alias)] = c
            self._canonical.setdefault(_norm(c), c)

    def normalize(self, raw: str) -> NormalizationResult:
        original = raw or ""
        key = _norm(original)
        if not key:
            return NormalizationResult(canonical="", matched=False, method="new", original=original)

        # 1. exact canonical
        if key in self._canonical:
            return NormalizationResult(
                canonical=self._canonical[key], matched=True, method="exact", original=original
            )

        # 2. alias
        if key in self._aliases:
            return NormalizationResult(
                canonical=self._aliases[key], matched=True, method="alias", original=original
            )

        # 3. fuzzy against canonicals then aliases (rapidfuzz token_sort_ratio)
        best_name: str | None = None
        best_score = 0.0
        for cand_key, cand in self._canonical.items():
            score = fuzz.ratio(key, cand_key)
            if score > best_score:
                best_score, best_name = score, cand
        if best_score < FUZZY_THRESHOLD:
            for cand_key, cand in self._aliases.items():
                score = fuzz.ratio(key, cand_key)
                if score > best_score:
                    best_score, best_name = score, cand

        if best_name is not None and best_score >= FUZZY_THRESHOLD:
            return NormalizationResult(
                canonical=best_name,
                matched=True,
                method="fuzzy",
                score=round(best_score, 1),
                original=original,
            )

        # 4. propose new — caller decides whether to create the Skill row
        return NormalizationResult(
            canonical=original.strip(), matched=False, method="new", original=original
        )


def build_db_normalizer(db) -> SkillNormalizer:
    """Construct from live DB rows: all canonical skills + DB alias rows."""
    names = [n for n in (db.query(Skill.name).all())] or []
    canonical = [n[0] if isinstance(n, tuple) else n for n in names]
    rows = db.query(SkillAlias.alias, Skill.name).join(
        Skill, SkillAlias.skill_id == Skill.id
    ).all()
    pairs = [(r[0], r[1]) for r in rows]

    normalizer = SkillNormalizer.from_yaml()
    normalizer.extend(canonical, pairs)
    return normalizer


def resolve_skill(db, raw: str, category: str | None = None) -> Skill:
    """Resolve raw text to a canonical Skill row, creating it if genuinely new.

    Uses the alias/fuzzy cascade; creation only happens when the cascade says
    "new" (plan §20 — LLM/curated aliases can be added later without data loss).
    """
    from sqlalchemy import select  # noqa: PLC0415

    normalizer = build_db_normalizer(db)
    result = normalizer.normalize(raw)

    skill = db.scalar(select(Skill).where(Skill.name == result.canonical))
    if skill is None:
        # case-insensitive second chance (canonical stored with different case)
        skill = db.scalar(select(Skill).where(Skill.name.ilike(result.canonical)))
    if skill is None:
        skill = Skill(
            name=result.canonical[:100],
            category=category.strip().lower() if category else None,
        )
        db.add(skill)
        db.flush()
        log.info("Created new skill %r (method=%s, input=%r)", skill.name, result.method, raw)
    return skill
