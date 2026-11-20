"""Location comparison shared by the heuristic scorer and the M2 ranker features.

Profile locations are free text ("Pune", "Pune, India", "Bangalore") while
Adzuna postings say "Pune, Maharashtra" / "Bengaluru, Karnataka". Comparing
whole strings (the old behaviour) almost never matched for Indian users, so the
"same city" and "same region" signals silently never fired.

Rules
  same_city    first comma segment equal after alias normalisation
               (Bangalore == Bengaluru, Bombay == Mumbai, ...)
  same_region  same Indian state (known city -> state table, or a state named
               in the string); otherwise the old last-segment rule, which keeps
               US-style "City, ST" data (the ranker's training data) unchanged.
"""

from __future__ import annotations

CITY_ALIASES = {
    "bangalore": "bengaluru", "bengalooru": "bengaluru", "bombay": "mumbai",
    "navi mumbai": "mumbai", "thane": "mumbai", "gurgaon": "gurugram", "calcutta": "kolkata",
    "madras": "chennai", "poona": "pune", "new delhi": "delhi", "delhi ncr": "delhi",
    "ncr": "delhi", "trivandrum": "thiruvananthapuram", "mysore": "mysuru",
    "cochin": "kochi", "baroda": "vadodara", "vizag": "visakhapatnam",
    "greater noida": "noida", "secunderabad": "hyderabad",
}

CITY_STATE = {
    "bengaluru": "karnataka", "mysuru": "karnataka", "mangaluru": "karnataka",
    "mumbai": "maharashtra", "pune": "maharashtra", "nagpur": "maharashtra", "nashik": "maharashtra",
    "delhi": "delhi", "noida": "uttar pradesh", "lucknow": "uttar pradesh", "kanpur": "uttar pradesh",
    "gurugram": "haryana", "faridabad": "haryana", "hyderabad": "telangana", "warangal": "telangana",
    "chennai": "tamil nadu", "coimbatore": "tamil nadu", "madurai": "tamil nadu",
    "kolkata": "west bengal", "ahmedabad": "gujarat", "vadodara": "gujarat", "surat": "gujarat",
    "jaipur": "rajasthan", "kochi": "kerala", "thiruvananthapuram": "kerala",
    "chandigarh": "chandigarh", "indore": "madhya pradesh", "bhopal": "madhya pradesh",
    "bhubaneswar": "odisha", "visakhapatnam": "andhra pradesh", "vijayawada": "andhra pradesh",
    "patna": "bihar", "guwahati": "assam", "dehradun": "uttarakhand", "goa": "goa",
}
STATES = set(CITY_STATE.values()) | {"punjab", "jharkhand", "chhattisgarh", "himachal pradesh",
                                     "jammu and kashmir"}


COUNTRIES = {"india", "in", "bharat", "united states", "usa", "us", "u.s.", "uk", "united kingdom"}


def _segments(loc: str | None) -> list[str]:
    """Comma parts, lowercased, with country names dropped (they say nothing about the city)."""
    segs = [s.strip().lower() for s in (loc or "").split(",") if s.strip()]
    kept = [s for s in segs if s not in COUNTRIES]
    return kept or segs


def city(loc: str | None) -> str:
    segs = _segments(loc)
    if not segs:
        return ""
    first = segs[0]
    return CITY_ALIASES.get(first, first)


def region(loc: str | None) -> str:
    """Indian state if identifiable, else the last comma segment (old rule)."""
    segs = _segments(loc)
    if not segs:
        return ""
    for s in segs:
        if s in STATES:
            return s
    c = city(loc)
    if c in CITY_STATE:
        return CITY_STATE[c]
    return segs[-1] if len(segs) > 1 else ""


def same_city(a: str | None, b: str | None) -> bool:
    """Same city name, and the regions agree when both are known
    (so "Springfield, IL" != "Springfield, MO", but "Pune" == "Pune, Maharashtra")."""
    ca, cb = city(a), city(b)
    if not (ca and cb and ca == cb):
        return False
    ra, rb = region(a), region(b)
    return not (ra and rb and ra != rb)


def same_region(a: str | None, b: str | None) -> bool:
    ra, rb = region(a), region(b)
    return bool(ra and rb and ra == rb)
