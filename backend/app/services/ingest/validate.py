"""Stage 5 — quality gates, deduplication and the run report (plan §20.1).

Gates (per plan): title non-empty, description ≥ 100 chars after cleaning,
at least one canonical skill found (flag when not — surfaced, never
fabricated), family assigned (checked by the orchestrator), salary_min ≤
salary_max.  Dedupe: (source, external_id) uniqueness plus cross-source
fuzzy signature match on normalised title + company.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

MIN_DESCRIPTION_CHARS = 100

_WS = re.compile(r"[^a-z0-9]+")

_NO_SKILL_FLAG = "no_canonical_skill_found"


def normalize_signature(*parts: str | None) -> str:
    """Normalised dedupe signature: lowercase, non-alnum collapsed."""
    return " ".join(_WS.sub(" ", p.lower()).strip() for p in parts if p).strip()


def quality_gates(posting: dict) -> list[str]:
    """Return gate violations for one cleaned+parsed posting (empty = pass)."""
    problems: list[str] = []
    title = (posting.get("title") or "").strip()
    if not title:
        problems.append("empty_title")

    description = posting.get("description") or ""
    if len(description) < MIN_DESCRIPTION_CHARS:
        problems.append(f"description_too_short({len(description)}<{MIN_DESCRIPTION_CHARS})")

    low = posting.get("salary_min")
    high = posting.get("salary_max")
    if low is not None and high is not None and low > high:
        problems.append("salary_min_gt_salary_max")
    if low is not None and low < 0:
        problems.append("negative_salary")

    return problems


@dataclass
class RunReport:
    """One pipeline run's counters + capped problem list (printed as JSON)."""

    source: str = "unknown"
    mode: str = "live"                 # "live" | "offline"
    fetched: int = 0
    cleaned: int = 0
    parsed: int = 0
    structured: int = 0
    gate_failed: int = 0
    no_skill_flagged: int = 0
    dup_skipped: int = 0
    new_jobs: int = 0
    updated_jobs: int = 0
    embedded: int = 0
    snapshot_rows: int = 0
    family_unassigned: int = 0
    errors: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    def flag(self, posting_id: str, why: str) -> None:
        if len(self.problems) < 200:
            self.problems.append(f"{posting_id}: {why}")

    def error(self, message: str) -> None:
        if len(self.errors) < 50:
            self.errors.append(message)

    def as_dict(self) -> dict:
        return asdict(self)


class DedupeBook:
    """Tracks seen (source, external_id) and title+company signatures."""

    def __init__(self) -> None:
        self._external: set[tuple[str, str]] = set()
        self._signatures: dict[str, tuple[str, str]] = {}

    @staticmethod
    def external_key(source: str, external_id: str) -> tuple[str, str]:
        return (source, external_id)

    def duplicate_reason(
        self,
        source: str,
        external_id: str | None,
        title: str | None,
        company: str | None,
    ) -> str | None:
        """None = keep; otherwise the skip reason."""
        if external_id:
            key = (source, external_id)
            if key in self._external:
                return f"dup_external({source}:{external_id})"

        signature = normalize_signature(title, company)
        if signature:
            first = self._signatures.get(signature)
            if first is not None:
                return f"dup_signature({first[0]}:{first[1]})"
        return None

    def remember(
        self,
        source: str,
        external_id: str | None,
        title: str | None,
        company: str | None,
    ) -> None:
        if external_id:
            self._external.add((source, external_id))
        signature = normalize_signature(title, company)
        if signature and signature not in self._signatures:
            self._signatures[signature] = (source, external_id or title or "?")
