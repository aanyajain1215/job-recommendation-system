"""Stage 2 — text cleaning (plan §20.1).

Deterministic: HTML → text, entity unescape, NFKC, whitespace collapse,
EEO boilerplate line removal.  Evidence-preserving: nothing is paraphrased;
only markup/boilerplate is dropped.
"""

from __future__ import annotations

import html
import re
import unicodedata

_TAG_RE = re.compile(r"<[^>]+>")
# Block-level tags imply a line break — preserve it before stripping tags so
# per-line passes (EEO removal) still work on HTML-escaped descriptions.
_BLOCK_RE = re.compile(r"<\s*(?:br\s*/?|/p|/li|/div|/h[1-6]|/tr)\s*>", re.IGNORECASE)
_WS_RE = re.compile(r"[ \t\xa0]+")

# Equal-opportunity / legal boilerplate lines removed by policy (plan §20).
EEO_PATTERNS: tuple[str, ...] = (
    "equal opportunity employer",
    "equal employment opportunity",
    "without regard to race",
    "without regard to religion",
    "all qualified applicants will receive consideration",
    "veteran status",
    "gender identity or expression",
    "we are an equal",
    "eoe/m/f/vets/disability",
    "discrimination based on",
)


def clean_text(raw: str | None) -> str:
    """Normalise one posting's free text. Empty input → empty string."""
    text = html.unescape(str(raw or ""))
    text = _BLOCK_RE.sub("\n", text)
    text = _TAG_RE.sub(" ", text)
    text = unicodedata.normalize("NFKC", text)

    lines: list[str] = []
    for line in text.splitlines():
        line = _WS_RE.sub(" ", line).strip()
        if not line:
            continue
        lowered = line.lower()
        if any(pattern in lowered for pattern in EEO_PATTERNS):
            continue
        lines.append(line)
    return "\n".join(lines)
