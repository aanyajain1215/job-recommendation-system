"""Natural-language job search (plan §15/§17, prompt P7).

Safety rails (§15): the LLM returns JSON **filters only** — it never touches
SQL.  Unknown fields are dropped against an explicit whitelist, enums are
validated by Pydantic, skills are canonicalized through the same normalizer
as structured filters, and ``min_salary`` is int-coerced.  The parsed filters
are echoed to the UI as editable chips: the user, not the LLM, is the final
authority.  Any failure degrades to treating the query as full-text search.

Hybrid ranking (§17): when a keyword query is present, results are fused
with Reciprocal Rank Fusion (k=60) over (a) ``ts_rank_cd`` order, (b) pgvector
KNN order on ``e_job``, (c) skill-set match count.  Deterministic tie-break:
recency, then job id.
"""

from __future__ import annotations

import logging
import math
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.enums import EmploymentType, ExperienceLevel
from app.models.job import Job
from app.models.job_family import JobFamily
from app.models.skill import JobSkill, Skill
from app.services.skill_normalizer import build_db_normalizer

log = logging.getLogger(__name__)

# Explicit P7 whitelist — anything else is dropped (plan §15).
ALLOWED_FIELDS: tuple[str, ...] = (
    "keywords",
    "location",
    "remote_only",
    "employment_type",
    "experience_level",
    "min_salary",
    "skills",
)

RRF_K = 60
CANDIDATE_CAP = 200


class SearchFilters(BaseModel):
    """Whitelisted P7 output; extra fields ignored by construction."""

    model_config = ConfigDict(extra="ignore")

    keywords: str | None = None
    location: str | None = None
    remote_only: bool = False
    employment_type: EmploymentType | None = None
    experience_level: ExperienceLevel | None = None
    min_salary: int | None = None
    skills: list[str] = Field(default_factory=list)


def sanitize(raw: dict[str, Any]) -> dict[str, Any]:
    """Drop every non-whitelisted field (used on raw dicts + tests)."""
    from app.services.llm.validators import validate_whitelisted

    clean = {
        k: v
        for k, v in (raw or {}).items()
        if k in ALLOWED_FIELDS
    }
    problems = validate_whitelisted(raw or {}, ALLOWED_FIELDS)
    if problems:
        log.info("P7 dropped non-whitelisted fields: %s", problems)
    return clean


def _coerce_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(float(str(value).replace(",", "").strip()))
    except (TypeError, ValueError):
        return None


def parse_query(q: str) -> tuple[SearchFilters, str]:
    """NL query -> (filters, mode). mode is "llm" or "fts" (fallback)."""
    text = (q or "").strip()
    if not text:
        return SearchFilters(), "fts"

    try:
        from app.services.llm.provider import get_provider, llm_available

        provider = get_provider() if llm_available() else None
    except Exception:  # pragma: no cover - provider import/config issues
        provider = None

    if provider is None:
        # Graceful degrade (plan §15): treat as plain full-text query.
        return SearchFilters(keywords=text), "fts"

    try:
        result, _usage = provider.complete_json(
            SearchFilters,
            _p7_prompt(text),
            route="nl_search",
        )
        filters = SearchFilters(**sanitize(result.model_dump()))
        coerced = _coerce_int(filters.min_salary)
        filters = filters.model_copy(
            update={
                "min_salary": coerced,
                "keywords": (filters.keywords or text).strip() or None,
                "skills": [s for s in (filters.skills or []) if str(s).strip()],
            }
        )
        if not any(
            [
                filters.keywords,
                filters.location,
                filters.remote_only,
                filters.employment_type,
                filters.experience_level,
                filters.min_salary is not None,
                filters.skills,
            ]
        ):
            # The model parsed nothing meaningful — fall back to FTS text.
            return SearchFilters(keywords=text), "fts"
        return filters, "llm"
    except Exception:
        log.info("P7 NL parse failed; falling back to FTS for %r", text)
        return SearchFilters(keywords=text), "fts"


def _p7_prompt(text: str) -> str:
    from app.services.llm.prompts import p7_nl_search

    return p7_nl_search(text)


def canonicalize_skills(db: Session, filters: SearchFilters) -> SearchFilters:
    """Canonicalize skill chips through the alias/fuzzy normalizer (no rows).

    Skills that don't resolve against the taxonomy are dropped: an unknown
    filter value must not zero out an entire result set silently — the
    parsed filters are echoed to the user as editable chips (§17).
    """
    if not filters.skills:
        return filters
    normalizer = build_db_normalizer(db)
    kept: list[str] = []
    for raw in filters.skills:
        raw = str(raw).strip()
        if not raw:
            continue
        try:
            result = normalizer.normalize(raw)
            # Unresolved chips come back matched=False with canonical=original
            # (the normalizer's "new skill" proposal) — drop them so an unknown
            # filter never silently zeroes a result set (§17).
            if getattr(result, "matched", False) and result.canonical:
                kept.append(str(result.canonical))
        except Exception:  # pragma: no cover - defensive
            continue
    # de-duplicate, preserve order
    seen: set[str] = set()
    ordered: list[str] = []
    for name in kept:
        key = name.lower()
        if key not in seen:
            seen.add(key)
            ordered.append(name)
    return filters.model_copy(update={"skills": ordered})


# ---------------------------------------------------------------------------
# Structured query builder shared with GET /jobs (§17: same builder)
# ---------------------------------------------------------------------------

# Query-side filler: words people use when phrasing a job search that match
# nearly every posting.  The FTS `english` dictionary strips prepositions but
# keeps content-noun fillers ("jobs", "hiring", "salary") — in an OR-of-tokens
# query they would match everything and dilute the rank.
_KEYWORD_FILLER = frozenset(
    {
        "job", "jobs", "hiring", "vacancy", "vacancies", "opening", "openings",
        "role", "roles", "position", "positions", "posting", "postings",
        "looking", "want", "wants", "need", "needs", "find", "finds", "search",
        "best", "top", "good", "near", "under", "within", "across", "around",
        "salary", "salaries", "pay", "paid", "stipend", "ctc", "package",
        "candidate", "candidates", "applicant", "applicants", "apply", "applied",
        "description", "about", "please", "show", "get", "give", "me", "my",
        "any", "all", "some", "more", "now", "today", "freshers", "fresher",
        "internship", "internships", "intern", "interns", "work", "working",
        # function words (kept out so every to_tsquery operand yields a lexeme)
        "in", "on", "at", "for", "to", "of", "the", "a", "an", "and", "or",
        "is", "are", "be", "by", "with", "from", "as", "that", "this", "it",
        "i", "we", "you", "who", "what", "how", "much", "many",
    }
)


def content_tokens(text: str) -> list[str]:
    """Sanitized search tokens for the OR fallback: lowercased, punctuation
    stripped, filler dropped; must be 2+ chars and contain a letter (so bare
    numbers like "20" never become search lexemes).  Order-preserving dedupe."""
    tokens: list[str] = []
    for raw in text.lower().split():
        tok = "".join(ch for ch in raw if ch.isalnum())
        if len(tok) < 2 or tok in _KEYWORD_FILLER:
            continue
        if not any(ch.isalpha() for ch in tok):
            continue
        if tok not in tokens:
            tokens.append(tok)
    return tokens


def build_filtered_query(db: Session, filters: SearchFilters):
    """Apply SearchFilters to the canonical published-jobs query.

    Returns (query, ts_rank_column_or_None) — the caller handles ordering.
    """
    from sqlalchemy import func, or_

    from app.models.enums import JobStatus

    query = (
        select(Job)
        .options(
            selectinload(Job.company),
            selectinload(Job.family),
            selectinload(Job.skills).joinedload(JobSkill.skill),
        )
        .where(Job.status == JobStatus.PUBLISHED)
    )

    rank_column = None
    text = (filters.keywords or "").strip()
    if text:
        tokens = content_tokens(text)
        if len(tokens) > 1:
            # Multi-word natural query: websearch_to_tsquery ANDs every word
            # and the ILIKE branch requires the whole phrase, so a fallback
            # sentence like "remote python jobs in bangalore" matched nothing
            # (verified live: 0 results).  OR the content tokens instead —
            # Postgres drops stopwords/empty operands, and ts_rank_cd rewards
            # documents matching more tokens, so densest matches rank first.
            tsquery = func.to_tsquery("english", " | ".join(tokens))
            token_matches = [
                or_(Job.title.ilike(f"%{t}%"), Job.description.ilike(f"%{t}%"))
                for t in tokens
            ]
            query = query.where(
                or_(Job.search_vector.op("@@")(tsquery), *token_matches)
            )
            rank_column = func.ts_rank_cd(Job.search_vector, tsquery)
        else:
            tsquery = func.websearch_to_tsquery("english", text)
            query = query.where(
                or_(
                    Job.search_vector.op("@@")(tsquery),
                    Job.title.ilike(f"%{text}%"),
                    Job.description.ilike(f"%{text}%"),
                )
            )
            rank_column = func.ts_rank_cd(Job.search_vector, tsquery)

    if filters.location:
        query = query.where(Job.location.ilike(f"%{filters.location.strip()}%"))
    if filters.remote_only:
        query = query.where(Job.is_remote.is_(True))
    if filters.employment_type:
        query = query.where(Job.employment_type == filters.employment_type)
    if filters.experience_level:
        query = query.where(Job.experience_level == filters.experience_level)
    if filters.min_salary:
        query = query.where(
            or_(Job.salary_max >= filters.min_salary, Job.salary_min >= filters.min_salary)
        )
    if filters.skills:
        normalizer = build_db_normalizer(db)
        for raw in filters.skills:
            canonical = normalizer.normalize(raw).canonical
            query = query.where(
                Job.skills.any(
                    JobSkill.skill.has(func.lower(Skill.name) == canonical.lower())
                )
            )
    return query, rank_column


# ---------------------------------------------------------------------------
# Hybrid RRF fusion (§17)
# ---------------------------------------------------------------------------

def rrf_scores(rank_lists: list[list[Any]], k: int = RRF_K) -> dict[Any, float]:
    """Reciprocal Rank Fusion: id -> Σ 1/(k + rank_i + 1).  Deterministic."""
    scores: dict[Any, float] = {}
    for order in rank_lists:
        for i, item_id in enumerate(order):
            scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (k + i + 1)
    return scores


def cosine(a: list[float] | None, b: list[float] | None) -> float:
    if not a or not b or len(a) != len(b):
        return -1.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na <= 0.0 or nb <= 0.0:
        return -1.0
    return dot / (na * nb)


def hybrid_rank(db: Session, jobs: list[Job], filters: SearchFilters) -> list[Job]:
    """RRF(k=60) over FTS order, KNN order, and skill-set match count.

    Orders that have no signal are skipped; ties break by recency then id
    (plan §17).  Input order must already be FTS-ranked (or recency for
    keyword-less queries).
    """
    if not jobs:
        return jobs

    lists: list[list[Any]] = []

    # (a) FTS order — input order from the SQL rank/created_at ordering.
    lists.append([j.id for j in jobs])

    # (b) KNN order on e_job vs. the query embedding.
    query_vec: list[float] | None = None
    text = (filters.keywords or "").strip()
    if text:
        try:
            from app.services.embeddings import get_embedder

            query_vec = get_embedder().encode_one(text)
        except Exception:  # pragma: no cover - embedder unavailable
            query_vec = None
    if query_vec:
        ensure = jobs  # embeddings already required by candidates here
        for job in ensure:
            if not job.embedding:
                try:
                    from app.services.embeddings import ensure_job_embedding

                    ensure_job_embedding(job)
                except Exception:  # pragma: no cover
                    pass
        knn_order = sorted(
            (j for j in jobs if j.embedding),
            key=lambda j: -cosine(query_vec, j.embedding),
        )
        lists.append([j.id for j in knn_order])

    # (c) skill-set match count (filter chips vs. job skills).
    wanted = {s.lower() for s in (filters.skills or []) if str(s).strip()}
    if wanted:
        def _count(job: Job) -> int:
            names = {
                js.skill.name.lower()
                for js in (job.skills or [])
                if js.skill is not None
            }
            return len(wanted & names)

        skill_order = sorted(jobs, key=lambda j: (-_count(j), str(j.id)))
        lists.append([j.id for j in skill_order])

    scores = rrf_scores(lists, k=RRF_K)

    def _key(job: Job):
        created = job.created_at
        ts = created.timestamp() if created is not None else 0.0
        # deterministic tie-break: score desc, recency desc, id asc
        return (-scores.get(job.id, 0.0), -ts, str(job.id))

    return sorted(jobs, key=_key)


def parsed_filters_dict(filters: SearchFilters) -> dict[str, Any]:
    """Echo shape for the UI chips (§17: user, not LLM, is the authority)."""
    data = filters.model_dump(mode="json")
    # Drop unset fields AND remote_only=False — an untouched default is not
    # something the user asked for, so it must not echo back as a chip.
    return {
        k: v
        for k, v in data.items()
        if v not in (None, [], "") and v is not False
    }
