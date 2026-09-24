"""Live job-ingestion pipeline (plan §20.1).

Seven stages — land → clean → parse → structure → gates/dedupe → embed →
snapshot.  Every stage here is pure (no network, no DB) so the pipeline is
unit-testable offline; `scripts/fetch_jobs_live.py` orchestrates stages and
handles I/O (HTTP landings, DB upsert, snapshot files, run reports).
"""

from app.services.ingest.clean import clean_text
from app.services.ingest.fetch import (
    fetch_all,
    provider_names,
    read_landing,
    write_landing,
)
from app.services.ingest.parse import (
    detect_employment_type,
    detect_remote,
    map_seniority,
    parse_location,
    parse_salary,
    parse_years,
)
from app.services.ingest.validate import (
    DedupeBook,
    RunReport,
    normalize_signature,
    quality_gates,
)

__all__ = [
    "DedupeBook",
    "RunReport",
    "clean_text",
    "detect_employment_type",
    "detect_remote",
    "fetch_all",
    "map_seniority",
    "normalize_signature",
    "parse_location",
    "parse_salary",
    "parse_years",
    "provider_names",
    "quality_gates",
    "read_landing",
    "write_landing",
]
