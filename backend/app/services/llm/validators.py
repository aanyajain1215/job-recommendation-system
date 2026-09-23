"""LLM output validators (plan §15 anti-hallucination contracts).

Pure functions returning a list of problems (empty = valid):

  * validate_spans        — evidence spans must slice to their quote AND the
                            quote must appear verbatim in the source text
  * validate_digits       — digit-multiset preservation: no output number may
                            contain a digit the source lacks (P5/P6 hours
                            can never be silently altered)
  * validate_skill_tokens — extracted skills must appear in the source text
                            (or in an explicitly allowed taxonomy)
  * validate_family       — classification must come from the family enum

Validators never repair and never trust: they only report, so the caller
(decidedly not the LLM) chooses whether to filter, flag, or fall back.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable, Sequence


def _digits(value: Any) -> Counter:
    return Counter(ch for ch in str(value) if ch.isdigit())


def digit_multiset_subset(candidate: Any, source: Any) -> bool:
    """True when every digit in `candidate` is covered by `source`'s digits."""
    cand, src = _digits(candidate), _digits(source)
    return all(src[d] >= n for d, n in cand.items())


def validate_digits(candidate: Any, source: Any, *, label: str = "value") -> list[str]:
    """Digit-multiset preservation: output digits ⊆ source digits (plan §15 P5)."""
    if digit_multiset_subset(candidate, source):
        return []
    return [
        f"{label}: digits are not preserved from source "
        f"(got {candidate!r}, source lacks some of those digits)"
    ]


def validate_spans(spans: Sequence[dict[str, Any]], source: str) -> list[str]:
    """Evidence spans must be real: quote in source, offsets slice to it."""
    problems: list[str] = []
    for i, span in enumerate(spans or []):
        span = span or {}
        quote = str(span.get("quote") or "")
        if not quote:
            problems.append(f"span[{i}]: empty quote")
            continue
        start, end = span.get("start"), span.get("end")
        if isinstance(start, int) and isinstance(end, int):
            if not (0 <= start < end <= len(source)):
                problems.append(f"span[{i}]: offsets [{start}:{end}] out of range")
                continue
            if source[start:end] != quote:
                problems.append(
                    f"span[{i}]: source[{start}:{end}] does not equal quote"
                )
                continue
        elif quote not in source:
            problems.append(f"span[{i}]: quote not found in source text")
            continue
        if quote not in source:
            problems.append(f"span[{i}]: quote not found in source text")
    return problems


def validate_skill_tokens(
    skills: Sequence[str],
    source: str,
    *,
    extra_allowed: Iterable[str] = (),
) -> list[str]:
    """Every extracted skill must literally appear in the source text, or be
    an explicitly allowed canonical name from the existing taxonomy."""
    src_l = " ".join(str(source).lower().split())
    allowed = {str(a).lower().strip() for a in extra_allowed if str(a).strip()}
    problems: list[str] = []
    for raw in skills or []:
        name = str(raw or "").strip()
        if not name:
            continue
        key = " ".join(name.lower().split())
        if key in src_l or key in allowed:
            continue
        problems.append(f"skill '{name}' does not appear in the source text")
    return problems


def validate_family(family: str, allowed: Iterable[str]) -> list[str]:
    """Classification must be one of the allowed families (plan §15 P4)."""
    key = str(family or "").lower().strip()
    allowed_set = {str(a).lower().strip() for a in allowed if str(a).strip()}
    if key and key in allowed_set:
        return []
    return [f"family '{family}' is not in the allowed taxonomy"]


def validate_whitelisted(filters: dict[str, Any], allowed_fields: Iterable[str]) -> list[str]:
    """P7: unknown filter fields are rejected (dropped by the caller)."""
    allowed = set(allowed_fields)
    return [
        f"field '{key}' is not whitelisted"
        for key in (filters or {})
        if key not in allowed
    ]
