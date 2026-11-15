"""Deterministic country/city detection for free-text job searches.

Users routinely type the country into the search box ("software engineer jobs
in Germany") instead of the structured location field.  The LLM parser is not
guaranteed to extract it (and the FTS fallback never does), so every result
set used to come back country-agnostic — Germany could sit below USA/Mexico.

This module is a small, offline gazetteer: it finds the first country/city
mentioned in a query, reports the Adzuna country code for live routing, and
exposes the match terms used to rank the requested country first.  No network,
no model, fully deterministic.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

# (Adzuna country code, canonical label, aliases)
_COUNTRY_DEFS: tuple[tuple[str | None, str, tuple[str, ...]], ...] = (
    ("in", "India", ("india", "indian", "bharat")),
    (
        "gb",
        "United Kingdom",
        (
            "united kingdom", "great britain", "britain", "uk", "u.k.",
            "england", "english", "scotland", "scottish", "wales", "welsh",
            "northern ireland",
        ),
    ),
    (
        "us",
        "United States",
        (
            "united states", "united states of america", "usa", "u.s.a.",
            "u.s.", "america", "american",
        ),
    ),
    ("ca", "Canada", ("canada", "canadian")),
    ("au", "Australia", ("australia", "australian", "aussie")),
    ("de", "Germany", ("germany", "german", "deutschland")),
    ("fr", "France", ("france", "french")),
    ("es", "Spain", ("spain", "spanish", "espana", "españa")),
    ("it", "Italy", ("italy", "italian", "italia")),
    ("nl", "Netherlands", ("netherlands", "holland", "dutch")),
    ("be", "Belgium", ("belgium", "belgian")),
    ("at", "Austria", ("austria", "austrian", "osterreich", "österreich")),
    ("ch", "Switzerland", ("switzerland", "swiss", "schweiz", "suisse")),
    ("pl", "Poland", ("poland", "polish", "polska")),
    ("pt", "Portugal", ("portugal", "portuguese")),
    ("mx", "Mexico", ("mexico", "mexican", "méxico")),
    ("br", "Brazil", ("brazil", "brazilian", "brasil")),
    ("sg", "Singapore", ("singapore", "singaporean")),
    ("nz", "New Zealand", ("new zealand", "nz", "aotearoa")),
    ("za", "South Africa", ("south africa", "south african")),
    # No Adzuna index today, but detecting these still keeps ranking honest
    # (and live search falls back to the configured index with `where=`).
    (None, "Ireland", ("ireland", "irish")),
    (None, "Sweden", ("sweden", "swedish", "sverige")),
    (None, "Norway", ("norway", "norwegian", "norge")),
    (None, "Denmark", ("denmark", "danish", "danmark")),
    (None, "Finland", ("finland", "finnish", "suomi")),
    (None, "Czech Republic", ("czech republic", "czechia", "czech")),
    (None, "Romania", ("romania", "romanian")),
    (None, "Bulgaria", ("bulgaria", "bulgarian")),
    (None, "Ukraine", ("ukraine", "ukrainian")),
    (None, "Russia", ("russia", "russian")),
    (None, "Turkey", ("turkey", "turkish", "türkiye", "turkiye")),
    (
        None,
        "United Arab Emirates",
        ("united arab emirates", "uae", "u.a.e.", "dubai", "abu dhabi"),
    ),
    (None, "Saudi Arabia", ("saudi arabia", "saudi", "riyadh", "jeddah")),
    (None, "Qatar", ("qatar", "doha")),
    (None, "Israel", ("israel", "israeli", "tel aviv", "jerusalem", "haifa")),
    (None, "Egypt", ("egypt", "egyptian", "cairo")),
    (None, "Nigeria", ("nigeria", "nigerian", "lagos", "abuja")),
    (None, "Kenya", ("kenya", "kenyan", "nairobi")),
    (None, "Ghana", ("ghana", "ghanaian", "accra")),
    (
        None,
        "Pakistan",
        ("pakistan", "pakistani", "karachi", "lahore", "islamabad"),
    ),
    (None, "Bangladesh", ("bangladesh", "bangladeshi", "dhaka")),
    (None, "Sri Lanka", ("sri lanka", "sri lankan", "colombo")),
    (None, "Nepal", ("nepal", "nepali", "kathmandu")),
    (
        None,
        "China",
        ("china", "chinese", "beijing", "shanghai", "shenzhen", "guangzhou"),
    ),
    (None, "Japan", ("japan", "japanese", "tokyo", "osaka", "kyoto")),
    (None, "South Korea", ("south korea", "korea", "korean", "seoul")),
    (None, "Hong Kong", ("hong kong", "hongkong")),
    (None, "Taiwan", ("taiwan", "taipei")),
    (None, "Malaysia", ("malaysia", "malaysian", "kuala lumpur")),
    (None, "Indonesia", ("indonesia", "indonesian", "jakarta")),
    (None, "Philippines", ("philippines", "filipino", "manila", "cebu")),
    (
        None,
        "Vietnam",
        ("vietnam", "vietnamese", "hanoi", "ho chi minh", "saigon"),
    ),
    (None, "Thailand", ("thailand", "thai", "bangkok")),
    (None, "Argentina", ("argentina", "argentinian", "buenos aires")),
    (None, "Chile", ("chile", "chilean", "santiago")),
    (None, "Colombia", ("colombia", "colombian", "bogota")),
    (None, "Peru", ("peru", "peruvian", "lima")),
    (None, "Uruguay", ("uruguay", "uruguayan", "montevideo")),
    (None, "Ecuador", ("ecuador", "ecuadorian", "quito")),
    (None, "Panama", ("panama", "panama city")),
)

# (canonical city label, Adzuna country code, country label, city aliases)
_CITY_DEFS: tuple[tuple[str, str | None, str, tuple[str, ...]], ...] = (
    # India
    ("Bengaluru", "in", "India", ("bengaluru", "bangalore")),
    ("Mumbai", "in", "India", ("mumbai", "bombay")),
    ("New Delhi", "in", "India", ("new delhi", "delhi")),
    ("Hyderabad", "in", "India", ("hyderabad",)),
    ("Pune", "in", "India", ("pune",)),
    ("Chennai", "in", "India", ("chennai", "madras")),
    ("Gurugram", "in", "India", ("gurugram", "gurgaon")),
    ("Noida", "in", "India", ("noida",)),
    ("Kolkata", "in", "India", ("kolkata", "calcutta")),
    ("Ahmedabad", "in", "India", ("ahmedabad",)),
    ("Jaipur", "in", "India", ("jaipur",)),
    ("Indore", "in", "India", ("indore",)),
    ("Kochi", "in", "India", ("kochi", "cochin")),
    ("Coimbatore", "in", "India", ("coimbatore",)),
    ("Chandigarh", "in", "India", ("chandigarh",)),
    ("Lucknow", "in", "India", ("lucknow",)),
    ("Thiruvananthapuram", "in", "India", ("thiruvananthapuram", "trivandrum")),
    ("Visakhapatnam", "in", "India", ("visakhapatnam", "vizag")),
    # United States
    ("New York", "us", "United States", ("new york", "new york city", "nyc")),
    ("San Francisco", "us", "United States", ("san francisco", "bay area")),
    ("Seattle", "us", "United States", ("seattle",)),
    ("Austin", "us", "United States", ("austin",)),
    ("Boston", "us", "United States", ("boston",)),
    ("Chicago", "us", "United States", ("chicago",)),
    ("Los Angeles", "us", "United States", ("los angeles",)),
    ("Denver", "us", "United States", ("denver",)),
    ("Atlanta", "us", "United States", ("atlanta",)),
    ("Dallas", "us", "United States", ("dallas",)),
    ("Houston", "us", "United States", ("houston",)),
    ("Miami", "us", "United States", ("miami",)),
    ("San Jose", "us", "United States", ("san jose",)),
    ("San Diego", "us", "United States", ("san diego",)),
    ("Philadelphia", "us", "United States", ("philadelphia",)),
    ("Phoenix", "us", "United States", ("phoenix",)),
    ("Portland", "us", "United States", ("portland",)),
    ("Washington", "us", "United States", ("washington dc", "washington")),
    ("Detroit", "us", "United States", ("detroit",)),
    ("Minneapolis", "us", "United States", ("minneapolis",)),
    ("Salt Lake City", "us", "United States", ("salt lake city",)),
    ("Raleigh", "us", "United States", ("raleigh",)),
    ("Charlotte", "us", "United States", ("charlotte",)),
    ("Nashville", "us", "United States", ("nashville",)),
    # United Kingdom
    ("London", "gb", "United Kingdom", ("london",)),
    ("Manchester", "gb", "United Kingdom", ("manchester",)),
    ("Birmingham", "gb", "United Kingdom", ("birmingham",)),
    ("Leeds", "gb", "United Kingdom", ("leeds",)),
    ("Edinburgh", "gb", "United Kingdom", ("edinburgh",)),
    ("Glasgow", "gb", "United Kingdom", ("glasgow",)),
    ("Bristol", "gb", "United Kingdom", ("bristol",)),
    ("Cambridge", "gb", "United Kingdom", ("cambridge",)),
    ("Oxford", "gb", "United Kingdom", ("oxford",)),
    ("Liverpool", "gb", "United Kingdom", ("liverpool",)),
    ("Sheffield", "gb", "United Kingdom", ("sheffield",)),
    ("Newcastle", "gb", "United Kingdom", ("newcastle",)),
    # Germany
    ("Berlin", "de", "Germany", ("berlin",)),
    ("Munich", "de", "Germany", ("munich", "munchen", "münchen")),
    ("Frankfurt", "de", "Germany", ("frankfurt",)),
    ("Hamburg", "de", "Germany", ("hamburg",)),
    ("Cologne", "de", "Germany", ("cologne", "koln", "köln")),
    ("Stuttgart", "de", "Germany", ("stuttgart",)),
    ("Dusseldorf", "de", "Germany", ("dusseldorf", "düsseldorf")),
    ("Dresden", "de", "Germany", ("dresden",)),
    ("Leipzig", "de", "Germany", ("leipzig",)),
    ("Nuremberg", "de", "Germany", ("nuremberg", "nurnberg")),
    # Canada
    ("Toronto", "ca", "Canada", ("toronto",)),
    ("Vancouver", "ca", "Canada", ("vancouver",)),
    ("Montreal", "ca", "Canada", ("montreal", "montréal")),
    ("Ottawa", "ca", "Canada", ("ottawa",)),
    ("Calgary", "ca", "Canada", ("calgary",)),
    ("Edmonton", "ca", "Canada", ("edmonton",)),
    ("Waterloo", "ca", "Canada", ("waterloo",)),
    # Australia
    ("Sydney", "au", "Australia", ("sydney",)),
    ("Melbourne", "au", "Australia", ("melbourne",)),
    ("Brisbane", "au", "Australia", ("brisbane",)),
    ("Perth", "au", "Australia", ("perth",)),
    ("Adelaide", "au", "Australia", ("adelaide",)),
    ("Canberra", "au", "Australia", ("canberra",)),
    # France
    ("Paris", "fr", "France", ("paris",)),
    ("Lyon", "fr", "France", ("lyon",)),
    ("Toulouse", "fr", "France", ("toulouse",)),
    ("Marseille", "fr", "France", ("marseille",)),
    ("Lille", "fr", "France", ("lille",)),
    ("Bordeaux", "fr", "France", ("bordeaux",)),
    # Netherlands
    ("Amsterdam", "nl", "Netherlands", ("amsterdam",)),
    ("Rotterdam", "nl", "Netherlands", ("rotterdam",)),
    ("Utrecht", "nl", "Netherlands", ("utrecht",)),
    ("Eindhoven", "nl", "Netherlands", ("eindhoven",)),
    ("The Hague", "nl", "Netherlands", ("the hague", "den haag")),
    # Spain
    ("Madrid", "es", "Spain", ("madrid",)),
    ("Barcelona", "es", "Spain", ("barcelona",)),
    ("Valencia", "es", "Spain", ("valencia",)),
    ("Seville", "es", "Spain", ("seville", "sevilla")),
    ("Bilbao", "es", "Spain", ("bilbao",)),
    ("Malaga", "es", "Spain", ("malaga", "málaga")),
    # Italy
    ("Rome", "it", "Italy", ("rome", "roma")),
    ("Milan", "it", "Italy", ("milan", "milano")),
    ("Turin", "it", "Italy", ("turin", "torino")),
    ("Florence", "it", "Italy", ("florence", "firenze")),
    ("Naples", "it", "Italy", ("naples", "napoli")),
    # Ireland
    ("Dublin", None, "Ireland", ("dublin",)),
    ("Cork", None, "Ireland", ("cork",)),
    ("Galway", None, "Ireland", ("galway",)),
    # Switzerland
    ("Zurich", "ch", "Switzerland", ("zurich", "zürich")),
    ("Geneva", "ch", "Switzerland", ("geneva", "genève", "geneve")),
    ("Basel", "ch", "Switzerland", ("basel",)),
    ("Bern", "ch", "Switzerland", ("bern",)),
    ("Lausanne", "ch", "Switzerland", ("lausanne",)),
    # Sweden / Nordics
    ("Stockholm", None, "Sweden", ("stockholm",)),
    ("Gothenburg", None, "Sweden", ("gothenburg", "goteborg", "göteborg")),
    ("Malmo", None, "Sweden", ("malmo", "malmö")),
    ("Oslo", None, "Norway", ("oslo",)),
    ("Copenhagen", None, "Denmark", ("copenhagen", "kobenhavn", "københavn")),
    ("Helsinki", None, "Finland", ("helsinki",)),
    # Poland / CEE
    ("Warsaw", "pl", "Poland", ("warsaw", "warszawa")),
    ("Krakow", "pl", "Poland", ("krakow", "kraków")),
    ("Wroclaw", "pl", "Poland", ("wroclaw", "wrocław")),
    ("Gdansk", "pl", "Poland", ("gdansk", "gdańsk")),
    ("Poznan", "pl", "Poland", ("poznan", "poznań")),
    ("Prague", None, "Czech Republic", ("prague", "praha")),
    ("Brno", None, "Czech Republic", ("brno",)),
    ("Bucharest", None, "Romania", ("bucharest", "bucuresti")),
    ("Cluj-Napoca", None, "Romania", ("cluj", "cluj-napoca")),
    ("Sofia", None, "Bulgaria", ("sofia",)),
    ("Kyiv", None, "Ukraine", ("kyiv", "kiev")),
    ("Lviv", None, "Ukraine", ("lviv",)),
    # Mexico / Brazil
    (
        "Mexico City",
        "mx",
        "Mexico",
        ("mexico city", "ciudad de mexico", "cdmx"),
    ),
    ("Guadalajara", "mx", "Mexico", ("guadalajara",)),
    ("Monterrey", "mx", "Mexico", ("monterrey",)),
    ("Sao Paulo", "br", "Brazil", ("sao paulo", "são paulo")),
    ("Rio de Janeiro", "br", "Brazil", ("rio de janeiro",)),
    ("Brasilia", "br", "Brazil", ("brasilia",)),
    ("Belo Horizonte", "br", "Brazil", ("belo horizonte",)),
    ("Curitiba", "br", "Brazil", ("curitiba",)),
    # NZ / South Africa
    ("Auckland", "nz", "New Zealand", ("auckland",)),
    ("Wellington", "nz", "New Zealand", ("wellington",)),
    ("Christchurch", "nz", "New Zealand", ("christchurch",)),
    ("Cape Town", "za", "South Africa", ("cape town",)),
    ("Johannesburg", "za", "South Africa", ("johannesburg", "joburg")),
    ("Durban", "za", "South Africa", ("durban",)),
    ("Pretoria", "za", "South Africa", ("pretoria",)),
    # Austria / Belgium / Portugal
    ("Vienna", "at", "Austria", ("vienna", "wien")),
    ("Salzburg", "at", "Austria", ("salzburg",)),
    ("Graz", "at", "Austria", ("graz",)),
    ("Brussels", "be", "Belgium", ("brussels", "bruxelles")),
    ("Antwerp", "be", "Belgium", ("antwerp", "antwerpen")),
    ("Ghent", "be", "Belgium", ("ghent",)),
    ("Lisbon", "pt", "Portugal", ("lisbon", "lisboa")),
    ("Porto", "pt", "Portugal", ("porto",)),
)


@dataclass(frozen=True)
class LocationHint:
    """A country/city mentioned in a free-text query."""

    label: str
    country: str
    country_code: str | None
    match_terms: tuple[str, ...]

    @property
    def is_country(self) -> bool:
        return self.label == self.country


def _dedupe(terms: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for term in terms:
        key = term.strip().lower()
        if key and key not in seen:
            seen.add(key)
            ordered.append(key)
    return tuple(ordered)


def _country_by_code() -> dict[str, tuple[str, tuple[str, ...]]]:
    return {
        code: (label, aliases)
        for code, label, aliases in _COUNTRY_DEFS
        if code
    }


def _build_entries() -> dict[str, LocationHint]:
    entries: dict[str, LocationHint] = {}

    # Cities per country, so a country query ("Germany") also matches job
    # locations that name only a city ("Berlin") and vice versa.
    city_terms_by_country: dict[str, list[str]] = {}
    for city, _code, country_label, aliases in _CITY_DEFS:
        city_terms_by_country.setdefault(country_label, []).extend([city, *aliases])

    for code, label, aliases in _COUNTRY_DEFS:
        if not label:
            continue
        terms = _dedupe([label, *aliases])
        hint = LocationHint(
            label=label,
            country=label,
            country_code=code or None,
            match_terms=_dedupe(
                [*terms, *city_terms_by_country.get(label, [])]
            ),
        )
        for term in terms:
            entries.setdefault(term, hint)

    countries = _country_by_code()
    for city, code, country_label, aliases in _CITY_DEFS:
        country_aliases: tuple[str, ...] = countries.get(code or "", (country_label, ()))[1]
        country_terms = _dedupe(
            [
                country_label,
                *country_aliases,
                *city_terms_by_country.get(country_label, []),
            ]
        )
        terms = _dedupe([city, *aliases])
        hint = LocationHint(
            label=city,
            country=country_label,
            country_code=code,
            match_terms=_dedupe([*terms, *country_terms]),
        )
        for term in terms:
            entries.setdefault(term, hint)

    return entries


_ENTRIES = _build_entries()

# Longest-first so "new zealand" is preferred over any shorter overlap.
_PHRASES: tuple[tuple[re.Pattern[str], LocationHint], ...] = tuple(
    (
        re.compile(rf"(?<!\w){re.escape(phrase)}(?!\w)", re.IGNORECASE),
        hint,
    )
    for phrase, hint in sorted(_ENTRIES.items(), key=lambda item: len(item[0]), reverse=True)
)


def find_location(text: str | None) -> tuple[str, LocationHint] | None:
    """Return (matched phrase, hint) for the earliest country/city mention."""
    hay = (text or "").strip()
    if not hay:
        return None

    best: tuple[re.Match[str], LocationHint] | None = None
    for pattern, hint in _PHRASES:
        match = pattern.search(hay)
        if match is None:
            continue
        if best is None:
            best = (match, hint)
            continue
        if match.start() < best[0].start():
            best = (match, hint)
        elif (
            match.start() == best[0].start()
            and len(match.group(0)) > len(best[0].group(0))
        ):
            best = (match, hint)
    if best is None:
        return None
    return best[0].group(0), best[1]


def detect_location(text: str | None) -> LocationHint | None:
    found = find_location(text)
    return found[1] if found else None


def strip_location(text: str | None, hint: LocationHint | None = None) -> str:
    """Remove the detected location phrase from a query (best effort)."""
    raw = (text or "").strip()
    if not raw:
        return ""
    found = find_location(raw)
    if found is None:
        return raw
    phrase, detected = found
    if hint is not None and detected.label != hint.label:
        return raw
    cleaned = re.sub(
        rf"(?<!\w){re.escape(phrase)}(?!\w)", " ", raw, count=1, flags=re.IGNORECASE
    )
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,.;-")
    cleaned = re.sub(
        r"^(?:in|at|near|across|around|from|within|the|a|an)\s+",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"(?:\s+(?:in|at|near|across|around|from|within|the|a|an))+$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    return re.sub(r"\s+", " ", cleaned).strip(" ,.;-")


@lru_cache(maxsize=1024)
def _term_pattern(term: str) -> re.Pattern[str]:
    return re.compile(rf"(?<!\w){re.escape(term)}(?!\w)", re.IGNORECASE)


def location_matches(job_location: str | None, hint: LocationHint | None) -> bool:
    """True when a job's location string names the hinted country/city."""
    if hint is None or not job_location:
        return False
    hay = str(job_location)
    return any(_term_pattern(term).search(hay) for term in hint.match_terms)
