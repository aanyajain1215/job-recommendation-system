#!/usr/bin/env python
"""Ingestion orchestrator — the 7-stage live preprocessing pipeline (plan §20.1).

    1. land      provider fetch (Adzuna primary + keyless supplements) or
                 offline golden corpus
    2. clean     HTML/entities/NFKC/EEO stripping (ingest.clean)
    3. parse     location/salary/seniority/employment/remote (ingest.parse)
    4. structure skill extraction (LLM P2 when --llm & available, else
                 deterministic keyword scan) + deterministic family assignment
    5. gates     quality gates + (source, external_id) & signature dedupe
    6. embed     MiniLM embeddings (DB mode only)
    7. snapshot  frozen corpus JSONL + machine-readable run report

Offline mode (`--offline`) lands `ml/data/golden/postings.jsonl` through the
*identical* stages — no network, fully deterministic (CI / no provider keys).

DB upsert is opt-in (`--upsert`): landings and snapshots never mutate the
shared corpus by default.  `run_pipeline` is the pure/testable core.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import yaml  # noqa: E402

from app.services.ingest import (  # noqa: E402
    DedupeBook,
    RunReport,
    clean_text,
    detect_employment_type,
    detect_remote,
    map_seniority,
    parse_location,
    parse_salary,
    parse_years,
    quality_gates,
)

GOLDEN_POSTINGS = BACKEND / "ml" / "data" / "golden" / "postings.jsonl"
RAW_DIR = BACKEND / "ml" / "data" / "raw"
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


# ---------------------------------------------------------------------------
# Stage 4 — structure: skills + family (deterministic core)
# ---------------------------------------------------------------------------

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


def llm_surfaces(title: str, description: str) -> list[str]:
    """Optional P2 LLM skill surfaces — fed through the same matcher."""
    try:
        from app.services.llm import get_provider, llm_available  # noqa: PLC0415
        from app.services.llm.prompts import p2_job_description  # noqa: PLC0415

        if not llm_available():
            return []
        provider = get_provider()
        if provider is None:
            return []

        from pydantic import BaseModel  # noqa: PLC0415

        class P2Skills(BaseModel):
            skills: list[str] = []

        payload, _usage = provider.complete_json(
            P2Skills,
            p2_job_description(f"{title}\n\n{description}"[:6000]),
            route="p2_job",
        )
        return [str(s) for s in payload.skills][:40]
    except Exception as exc:  # noqa: BLE001 - LLM is strictly optional
        print(f"[llm] p2 structure unavailable: {exc}", file=sys.stderr)
        return []


def assign_family(title: str, families: list[dict]) -> str | None:
    """Deepest-family-first keyword match on the title (seed_canonical order)."""
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
    return None


def load_families() -> list[dict]:
    if not FAMILIES_YAML.exists():
        return []
    return yaml.safe_load(FAMILIES_YAML.read_text(encoding="utf-8")) or []


# ---------------------------------------------------------------------------
# Stage 7 — snapshot
# ---------------------------------------------------------------------------

def write_snapshot(dest: Path, rows: list[dict], stamp: str) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / f"corpus-{stamp}.jsonl"
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path


# ---------------------------------------------------------------------------
# Pipeline core (pure except optional DB upsert) — exercised by tests
# ---------------------------------------------------------------------------

def run_pipeline(
    postings: list[dict],
    *,
    dest: Path,
    mode: str = "offline",
    pairs: list[tuple[str, str]] | None = None,
    families: list[dict] | None = None,
    use_llm: bool = False,
    upsert_db: bool = False,
    stamp: str | None = None,
) -> dict:
    """Stages 2–7 over already-landed postings. Returns report + snapshot path."""
    stamp = stamp or datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    source_label = "mixed"
    report = RunReport(source=source_label, mode=mode)
    pairs = load_surface_pairs() if pairs is None else pairs
    if use_llm:
        extra = [(s, s) for s in set(sum((llm_surfaces(p.get("title", ""), p.get("description", "")) for p in postings), []))]
        pairs = pairs + extra
    families = load_families() if families is None else families

    dedupe = DedupeBook()
    kept: list[dict] = []

    for raw in postings:
        report.fetched += 1
        source = str(raw.get("source") or "synthetic")
        external_id = str(raw.get("external_id") or raw.get("id") or f"row-{report.fetched}")
        title = clean_text(raw.get("title"))
        description = clean_text(raw.get("description"))
        report.cleaned += 1

        # ---- stage 3: parse ----
        explicit_min = raw.get("salary_min")
        explicit_max = raw.get("salary_max")
        currency = raw.get("currency")
        if explicit_min is not None and explicit_max is not None:
            smin, smax = int(explicit_min), int(explicit_max)
            cur = currency or resolve_currency(source)
            if smin > smax:
                smin, smax = smax, smin
        else:
            salary_text = raw.get("salary_text") or f"{raw.get('salary')} {title}"
            smin, smax, cur = parse_salary(
                str(salary_text), default_currency=currency or resolve_currency(source)
            )

        location = parse_location(raw.get("location"))
        years = parse_years(description)
        level = map_seniority(title, years)
        remote = bool(raw.get("is_remote")) or detect_remote(title, description, location)
        employment = detect_employment_type(f"{title} {description[:400]}")
        report.parsed += 1

        posting = {
            "source": source,
            "external_id": external_id,
            "title": title,
            "description": description,
            "company": str(raw.get("company") or "Unknown"),
            "location": location,
            "is_remote": remote,
            "salary_min": smin,
            "salary_max": smax,
            "currency": cur,
            "url": str(raw.get("url") or ""),
            "posted_at": str(raw.get("posted_at") or ""),
            "experience_level": level.value,
            "employment_type": employment.value,
        }

        # ---- stage 5a: quality gates ----
        problems = quality_gates(posting)
        if problems:
            report.gate_failed += 1
            report.flag(external_id, "; ".join(problems))
            continue

        # ---- stage 4: structure (skills + family) ----
        skills = extract_skills(title, description, pairs)
        if not skills:
            report.no_skill_flagged += 1
            report.flag(external_id, "no_canonical_skill_found")
        family = assign_family(title, families)
        if family is None:
            report.family_unassigned += 1
        posting["skills"] = [{"name": name, "is_required": req} for name, req in skills]
        posting["family"] = family
        report.structured += 1

        # ---- stage 5b: dedupe ----
        reason = dedupe.duplicate_reason(source, external_id, title, posting["company"])
        if reason is not None:
            report.dup_skipped += 1
            report.flag(external_id, reason)
            continue
        dedupe.remember(source, external_id, title, posting["company"])

        kept.append(posting)

    # ---- stage 7: snapshot (stage 6 embed happens in DB mode) ----
    snapshot = write_snapshot(dest, kept, stamp)
    report.snapshot_rows = len(kept)

    if upsert_db and kept:
        try:
            embedded = upsert_jobs(kept, report)
            report.embedded = embedded
        except Exception as exc:  # noqa: BLE001 - report, don't crash the run
            report.error(f"db upsert failed: {exc}")

    report_path = dest / f"run-{stamp}.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report.as_dict(), indent=2), encoding="utf-8")

    return {"report": report.as_dict(), "kept": kept, "snapshot": str(snapshot), "run_report": str(report_path)}


# ---------------------------------------------------------------------------
# DB upsert (stage 6 + persistence) — opt-in
# ---------------------------------------------------------------------------

def upsert_jobs(rows: list[dict], report: RunReport) -> int:
    """Upsert postings into jobs with company/poster/skills/family/embeddings.

    Only *existing* canonical skills are linked (ingestion never mints new
    Skill rows — alias proposals belong to the admin flow, plan §18).
    Returns the number of jobs that needed embedding.
    """
    from sqlalchemy import select  # noqa: PLC0415

    from app.core.db import SessionLocal  # noqa: PLC0415
    from app.models.company import Company  # noqa: PLC0415
    from app.models.enums import (  # noqa: PLC0415
        EmploymentType,
        ExperienceLevel,
        JobStatus,
        UserRole,
    )
    from app.models.job import Job  # noqa: PLC0415
    from app.models.job_family import JobFamily  # noqa: PLC0415
    from app.models.skill import JobSkill, Skill  # noqa: PLC0415
    from app.models.user import User  # noqa: PLC0415
    from app.services.embeddings import ensure_job_embeddings  # noqa: PLC0415

    db = SessionLocal()
    created_or_updated = 0
    try:
        # system poster account + one company per source
        poster = db.scalar(select(User).where(User.email == "ingest@jobrec.local"))
        if poster is None:
            from argon2 import PasswordHasher  # noqa: PLC0415
            import secrets  # noqa: PLC0415

            poster = User(
                email="ingest@jobrec.local",
                hashed_password=PasswordHasher().hash(secrets.token_urlsafe(24)),
                role=UserRole.EMPLOYER,
                is_active=True,
                is_verified=True,
            )
            db.add(poster)
            db.flush()

        companies: dict[str, Company] = {}   # per-source feed fallback (no employer name)
        employers: dict[str, Company] = {}    # per-employer-name cache
        skill_by_name = {
            s.name.lower(): s.id for s in db.scalars(select(Skill)).all()
        }
        family_by_name = {
            f.name: f.id for f in db.scalars(select(JobFamily)).all()
        }

        for row in rows:
            source = row["source"]

            # Company: the real employer when the provider sent one (get-or-create,
            # slug collisions suffixed); per-source feed company otherwise.
            # Re-resolved on every run so rows ingested before employer names
            # existed migrate on the next upsert.
            employer = (row.get("company") or "").strip()
            if employer and not employer.lower().startswith("unknown"):
                company = employers.get(employer.lower())
                if company is None:
                    slug = (
                        re.sub(r"[^a-z0-9]+", "-", employer.lower()).strip("-")[:48]
                        or "company"
                    )
                    base, n = slug, 2
                    existing = db.scalar(
                        select(Company).where(Company.slug == slug)
                    )
                    while (
                        existing is not None
                        and existing.name.lower() != employer.lower()
                    ):
                        slug = f"{base}-{n}"
                        n += 1
                        existing = db.scalar(
                            select(Company).where(Company.slug == slug)
                        )
                    if existing is None:
                        company = Company(
                            name=employer,
                            slug=slug,
                            description=(
                                f"Employer ingested from the {source} provider (plan §20)."
                            ),
                            created_by_user_id=poster.id,
                        )
                        db.add(company)
                        db.flush()
                    else:
                        company = existing
                    employers[employer.lower()] = company
            else:
                company = companies.get(source)
                if company is None:
                    company = db.scalar(
                        select(Company).where(Company.slug == f"feed-{source}")
                    )
                    if company is None:
                        company = Company(
                            name=f"{source.capitalize()} Feed",
                            slug=f"feed-{source}",
                            description=f"Jobs ingested from the {source} provider (plan §20).",
                            created_by_user_id=poster.id,
                        )
                        db.add(company)
                        db.flush()
                    companies[source] = company

            job = db.scalar(
                select(Job).where(
                    Job.source == source, Job.external_id == row["external_id"]
                )
            )
            is_new = job is None
            if job is None:
                job = Job(
                    source=source,
                    external_id=row["external_id"],
                    posted_by_user_id=poster.id,
                    company_id=company.id,
                    status=JobStatus.PUBLISHED,
                )
                db.add(job)

            job.company_id = company.id
            job.title = row["title"][:200]
            job.description = row["description"]
            job.location = row["location"] or "Remote"
            job.is_remote = bool(row["is_remote"])
            job.salary_min = row["salary_min"]
            job.salary_max = row["salary_max"]
            job.salary_currency = row["currency"] or resolve_currency(source)
            job.external_url = row["url"][:500] or None
            job.experience_level = ExperienceLevel(row["experience_level"])
            job.employment_type = EmploymentType(row["employment_type"])
            job.family_id = family_by_name.get(row.get("family") or "")
            db.flush()

            if is_new:
                for requirement in row.get("skills") or []:
                    skill_id = skill_by_name.get(str(requirement["name"]).lower())
                    if skill_id is None:
                        continue
                    db.add(
                        JobSkill(
                            job_id=job.id,
                            skill_id=skill_id,
                            is_required=bool(requirement.get("is_required", True)),
                            importance_weight=1.0,
                        )
                    )
            created_or_updated += 1
            if is_new:
                report.new_jobs += 1
            else:
                report.updated_jobs += 1

        db.commit()

        # stage 6: embeddings for freshly created jobs
        fresh = db.scalars(
            select(Job).where(Job.source.in_({r["source"] for r in rows}),
                              Job.embedding.is_(None))
        ).all()
        if fresh:
            ensure_job_embeddings(fresh)
            db.commit()
        return len(fresh)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def land(mode: str, query: str) -> tuple[list[dict], dict[str, str]]:
    """Stage 1: live providers or the offline golden corpus."""
    if mode == "offline":
        from app.services.ingest.fetch import read_landing  # noqa: PLC0415

        if not GOLDEN_POSTINGS.exists():
            raise SystemExit(
                "golden corpus missing — run: python scripts/synthesize_corpus.py"
            )
        return read_landing(GOLDEN_POSTINGS), {}

    from app.services.ingest.fetch import fetch_all, write_landing  # noqa: PLC0415

    postings, errors = fetch_all(query)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    run_dir = RAW_DIR / stamp
    if postings:
        write_landing(run_dir, "landing", postings)
    return postings, errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="7-stage live ingestion pipeline (plan §20.1)")
    parser.add_argument("--offline", action="store_true", help="land the golden corpus instead of HTTP")
    parser.add_argument("--query", default="python developer", help="provider search query")
    parser.add_argument("--upsert", action="store_true", help="persist into jobs (opt-in!)")
    parser.add_argument("--llm", action="store_true", help="P2 LLM structure stage (else keyword scan)")
    parser.add_argument("--dest", default=str(RAW_DIR), help="snapshot/report destination")
    args = parser.parse_args(argv)

    mode = "offline" if args.offline else "live"
    postings, errors = land(mode, args.query)

    result = run_pipeline(
        postings,
        dest=Path(args.dest),
        mode=mode,
        use_llm=args.llm,
        upsert_db=args.upsert,
    )
    for provider, message in errors.items():
        result["report"].setdefault("provider_errors", {})[provider] = message

    print(json.dumps(result["report"], indent=2))
    print(f"snapshot: {result['snapshot']}", file=sys.stderr)
    if errors and not postings:
        print(
            "all providers failed — rerun with --offline to process the golden corpus",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
