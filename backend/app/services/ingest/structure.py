"""Stage 4 — structure: skill surfaces + family assignment (pure, no I/O).

Moved out of `scripts/fetch_jobs_live.py` so request-path code (live Adzuna
search, plan "query-time ingestion") can reuse the *same* deterministic
structurer the offline pipeline uses — one source of truth for skill
extraction and job→family assignment.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

# Repo/backend root: app/services/ingest/structure.py -> parents[3] == backend/
BACKEND = Path(__file__).resolve().parents[3]
FAMILIES_YAML = BACKEND / "ml" / "data" / "families.yaml"
ALIASES_YAML = BACKEND / "ml" / "data" / "skill_aliases.yaml"

# ---------------------------------------------------------------------------
# Currency resolution (fix: INR postings were stored as USD)
# ---------------------------------------------------------------------------
# Geo-targeted providers (Adzuna) omit a currency field — values arrive in
# the endpoint country's currency.  Defaulting to USD mislabeled every
# Indian posting (₹3L stored as "USD 300000"), which skewed both the UI and
# the salary scoring component.  Resolve from the provider's country instead.

_ADZUNA_CURRENCY = {
    "in": "INR", "gb": "GBP", "us": "USD", "ca": "CAD", "au": "AUD",
    "at": "EUR", "be": "EUR", "ch": "CHF", "de": "EUR", "es": "EUR",
    "fr": "EUR", "it": "EUR", "mx": "MXN", "nl": "EUR", "nz": "NZD",
    "pl": "PLN", "pt": "EUR", "sg": "SGD",
}


def resolve_currency(source: str) -> str:
    """Provider+country implied currency when the API response omits one."""
    if source == "adzuna":
        from app.core.config import get_settings

        country = (get_settings().adzuna_country or "in").lower()
        return _ADZUNA_CURRENCY.get(country, "INR")
    return "USD"


PREFERRED_MARKERS = (
    "nice to have",
    "good to have",
    "preferred qualifications",
    "preferred skills",
    "preferred qualifications",
    "bonus points",
    "would be nice",
    "bonus skills",
)


def load_surface_pairs() -> list[tuple[str, str]]:
    """(surface, canonical) pairs from the curated YAML — the offline stand-in
    for the DB alias table (same source of truth, seed_canonical loads it)."""
    pairs: list[tuple[str, str]] = []
    if ALIASES_YAML.exists():
        data = yaml.safe_load(ALIASES_YAML.read_text(encoding="utf-8")) or {}
        for canonical, aliases in (data or {}).items():
            pairs.append((str(canonical).lower(), str(canonical)))
            for alias in aliases or []:
                pairs.append((str(alias).lower(), str(canonical)))
    if FAMILIES_YAML.exists():
        for fam in yaml.safe_load(FAMILIES_YAML.read_text(encoding="utf-8")) or []:
            for skill in fam.get("core_skills") or []:
                pairs.append((str(skill).lower(), str(skill)))
    # de-dupe while preserving order
    seen: set[tuple[str, str]] = set()
    unique: list[tuple[str, str]] = []
    for pair in pairs:
        if pair not in seen:
            seen.add(pair)
            unique.append(pair)
    return unique


def _preferred_marker_index(text_lower: str) -> int:
    hits = [text_lower.find(m) for m in PREFERRED_MARKERS]
    hits = [i for i in hits if i != -1]
    return min(hits) if hits else -1


def extract_skills(
    title: str, description: str, pairs: list[tuple[str, str]]
) -> list[tuple[str, bool]]:
    """Word-boundary surface scan → [(canonical, is_required)].

    Hits inside a "nice to have" section are marked preferred; a skill that
    also appears before the marker stays required.  Deterministic — the LLM
    (stage 4 --llm) only contributes *extra surfaces* to this same matcher,
    never direct writes.
    """
    text = f"{title}\n{description}".lower()
    marker = _preferred_marker_index(text)
    out: dict[str, tuple[str, bool]] = {}
    for surface, canonical in pairs:
        surface = surface.lower()
        if len(surface) < 2:
            continue
        pattern = rf"(?<![a-z0-9+.#]){re.escape(surface)}(?![a-z0-9+.#])"
        match = re.search(pattern, text)
        if not match:
            continue
        required = not (marker != -1 and match.start() > marker)
        key = canonical.lower()
        if key in out:
            prev_canonical, prev_required = out[key]
            out[key] = (prev_canonical, prev_required or required)
        else:
            out[key] = (canonical, required)
    return [(canonical, required) for canonical, required in out.values()]


def assign_family(title: str, families: list[dict], *, use_llm: bool = False) -> str | None:
    """Deepest-family-first keyword match on the title; optional LLM fallback (P4)."""
    def depth(fam: dict) -> int:
        d, seen = 0, set()
        parent = fam.get("parent")
        while parent and parent not in seen:
            seen.add(parent)
            d += 1
            parent = next(
                (f.get("parent") for f in families if f.get("name") == parent), None
            )
        return d

    ordered = sorted(families, key=lambda f: (-depth(f), f.get("name") or ""))
    title_low = (title or "").lower()
    for fam in ordered:
        keywords = sorted(
            (str(k).lower() for k in (fam.get("keywords") or [])), key=len, reverse=True
        )
        hit = next((kw for kw in keywords if kw and kw in title_low), None)
        if hit:
            return fam.get("name")

    if use_llm and title_low:
        try:
            from pydantic import BaseModel
            from app.services.llm import get_provider, mark_flagged, prompts, validators

            provider = get_provider()
            if provider is not None:
                allowed = [str(f.get("name")) for f in families if f.get("name")]
                if "other" not in [a.lower() for a in allowed]:
                    allowed = allowed + ["other"]

                class _FamilyOut(BaseModel):
                    family: str

                out, usage = provider.complete_json(
                    _FamilyOut,
                    prompts.p4_title_to_family(str(title), allowed),
                    system="Classify the job title into exactly one allowed family.",
                    max_tokens=80,
                    route="P4",
                )
                problems = validators.validate_family(out.family, allowed)
                if problems:
                    mark_flagged(usage, "; ".join(problems))
                else:
                    fam = str(out.family).strip()
                    # return canonical-cased name from allowed list
                    for a in allowed:
                        if a.lower() == fam.lower():
                            return None if a.lower() == "other" else a
        except Exception:
            pass
    return None


def load_families() -> list[dict]:
    if not FAMILIES_YAML.exists():
        return []
    return yaml.safe_load(FAMILIES_YAML.read_text(encoding="utf-8")) or []
