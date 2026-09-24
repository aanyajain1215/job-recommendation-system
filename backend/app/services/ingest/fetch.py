"""Stage 1 — landing fetchers (plan §20.1).

Providers: Adzuna is primary (needs ADZUNA_APP_ID/KEY), Arbeitnow / Remotive
/ Jobicy are keyless supplements (LinkedIn excluded by policy, §2).  Every
adapter normalises to one raw posting dict:

    source, external_id, title, description, company, location,
    salary_min, salary_max, currency, url, posted_at, is_remote

HTTP via stdlib urllib (no extra dependency), polite delay between requests,
resumable per-run landings (already-landed ids are skipped).  Network
failures never raise out of `fetch_all` — they land in the returned error
map so the orchestrator can fall back to the offline golden corpus.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.parse
import urllib.request
from pathlib import Path

from app.core.config import get_settings

log = logging.getLogger(__name__)

USER_AGENT = "JobRecIngest/1.0 (+https://localhost; career-intelligence-demo)"

PROVIDERS = ("adzuna", "arbeitnow", "remotive", "jobicy")


def provider_names() -> tuple[str, ...]:
    return PROVIDERS


def _get_json(url: str, params: dict | None = None, timeout: int = 20) -> dict:
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - fixed API hosts
        return json.loads(resp.read().decode("utf-8"))


# ---------------------------------------------------------------------------
# Provider adapters → raw posting dict
# ---------------------------------------------------------------------------

def fetch_adzuna(query: str, page: int = 1) -> list[dict]:
    settings = get_settings()
    if not (settings.adzuna_app_id and settings.adzuna_app_key):
        raise RuntimeError("ADZUNA_APP_ID/ADZUNA_APP_KEY not configured")
    country = settings.adzuna_country or "in"
    url = f"https://api.adzuna.com/v1/api/jobs/{country}/search/{page}"
    data = _get_json(
        url,
        {
            "app_id": settings.adzuna_app_id,
            "app_key": settings.adzuna_app_key,
            "content-type": "application/json",
            "results_per_page": 25,
            "what": query,
            "full_time": 1,
        },
        timeout=settings.ingest_http_timeout,
    )
    out: list[dict] = []
    for row in data.get("results", []):
        company = row.get("company") or {}
        location = row.get("location") or {}
        out.append(
            {
                "source": "adzuna",
                "external_id": str(row.get("id") or ""),
                "title": row.get("title") or "",
                "description": row.get("description") or "",
                "company": company.get("display_name") or "Unknown",
                "location": location.get("display_name") or "",
                "salary_min": row.get("salary_min"),
                "salary_max": row.get("salary_max"),
                "currency": None,  # Adzuna returns local currency — parsed from text/geo later
                "url": row.get("redirect_url") or "",
                "posted_at": row.get("created") or "",
                "is_remote": "remote" in ((row.get("title") or "") + (location.get("display_name") or "")).lower(),
            }
        )
    return out


def fetch_arbeitnow(query: str, page: int = 1) -> list[dict]:
    data = _get_json("https://www.arbeitnow.com/api/job-api", {"page": page})
    out: list[dict] = []
    for row in data.get("data", []):
        title = row.get("title") or ""
        if query and query.split()[0].lower() not in f"{title} {row.get('description') or ''}".lower():
            # keyless feeds have no server-side query — light client-side filter
            continue
        out.append(
            {
                "source": "arbeitnow",
                "external_id": str(row.get("slug") or row.get("url") or title)[:120],
                "title": title,
                "description": row.get("description") or "",
                "company": row.get("company_name") or "Unknown",
                "location": row.get("location") or "",
                "salary_min": None,
                "salary_max": None,
                "currency": None,
                "url": row.get("url") or "",
                "posted_at": str(row.get("posted_at_utc") or row.get("posted_at") or ""),
                "is_remote": "remote" in (row.get("location") or "").lower(),
            }
        )
    return out


def fetch_remotive(query: str, page: int = 1) -> list[dict]:
    params: dict = {"limit": 50}
    if query:
        params["search"] = query
    data = _get_json("https://remotive.com/api/remote-jobs", params)
    out: list[dict] = []
    for row in data.get("remote_jobs", []):
        salary_text = row.get("salary") or ""
        out.append(
            {
                "source": "remotive",
                "external_id": str(row.get("id") or ""),
                "title": row.get("title") or "",
                "description": row.get("description") or "",
                "company": row.get("company_name") or "Unknown",
                "location": row.get("candidate_required_location") or "Remote",
                "salary_min": None,          # salary is free text → parsed at stage 3
                "salary_max": None,
                "currency": None,
                "salary_text": salary_text,
                "url": row.get("url") or "",
                "posted_at": row.get("publication_date") or "",
                "is_remote": True,
            }
        )
    return out


def fetch_jobicy(query: str, page: int = 1) -> list[dict]:
    params: dict = {"count": 20}
    if query:
        params["tag"] = query.split()[0]
    data = _get_json("https://jobicy.com/api/v2/remote-jobs", params)
    out: list[dict] = []
    for row in data.get("jobs", []):
        out.append(
            {
                "source": "jobicy",
                "external_id": str(row.get("id") or row.get("url") or ""),
                "title": row.get("jobTitle") or "",
                "description": row.get("jobDesc") or "",
                "company": row.get("companyName") or "Unknown",
                "location": row.get("jobGeo") or row.get("jobCity") or "Remote",
                "salary_min": row.get("annualSalaryMin"),
                "salary_max": row.get("annualSalaryMax"),
                "currency": "USD" if row.get("annualSalaryMin") else None,
                "url": row.get("url") or "",
                "posted_at": row.get("pubDate") or "",
                "is_remote": True,
            }
        )
    return out


_FETCHERS = {
    "adzuna": fetch_adzuna,
    "arbeitnow": fetch_arbeitnow,
    "remotive": fetch_remotive,
    "jobicy": fetch_jobicy,
}


# ---------------------------------------------------------------------------
# Landing files (immutable per run)
# ---------------------------------------------------------------------------

def write_landing(dest: Path, source: str, postings: list[dict]) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / f"{source}.jsonl"
    with path.open("w", encoding="utf-8") as fh:
        for posting in postings:
            fh.write(json.dumps(posting, ensure_ascii=False) + "\n")
    return path


def read_landing(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def fetch_all(
    query: str,
    providers: tuple[str, ...] | None = None,
    *,
    max_per_provider: int = 75,
    pages: int = 3,
) -> tuple[list[dict], dict[str, str]]:
    """Land from every requested provider. Returns (postings, errors).

    Never raises: a failing provider is recorded in `errors` and skipped.
    """
    settings = get_settings()
    chosen = providers or PROVIDERS
    landed: list[dict] = []
    errors: dict[str, str] = {}

    for name in chosen:
        fetcher = _FETCHERS.get(name)
        if fetcher is None:
            errors[name] = "unknown provider"
            continue
        try:
            provider_rows: list[dict] = []
            seen: set[str] = set()
            for page in range(1, pages + 1):
                batch = fetcher(query, page)
                if not batch:
                    break
                fresh = [r for r in batch if r.get("external_id") not in seen]
                if not fresh:
                    break  # keyless feeds often ignore paging — stop on repeat
                for r in fresh:
                    seen.add(r.get("external_id") or "")
                provider_rows.extend(fresh)
                if len(provider_rows) >= max_per_provider:
                    break
                if settings.ingest_delay_seconds:
                    time.sleep(settings.ingest_delay_seconds)
            landed.extend(provider_rows[:max_per_provider])
        except Exception as exc:  # noqa: BLE001 - provider isolation by design
            log.info("provider %s failed: %s", name, exc)
            errors[name] = str(exc)

    return landed, errors
