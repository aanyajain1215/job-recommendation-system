#!/usr/bin/env python
"""One-off purge of the pre-loaded ingestion corpus (live-data conversion).

The platform now serves jobs two ways only: employers post their own
listings (native rows), and every search hits Adzuna at query time.  This
script removes everything the offline ingestion wrote:

  1. jobs posted by the ingest service account (or any non-native source)
     — applications, interactions, job_skills, recommendations, skill_gaps
     and feedback rows referencing them cascade away;
  2. companies created by the ingest account;
  3. the ingest@jobrec.local service account (its profile, applications,
     interactions and system_config credit cascade / null out with it).

Employer accounts, seeker accounts (including the seeded demo seekers that
back the E1–E5 pipelines) and native platform postings are untouched.
Idempotent: a second run reports zeros.
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from sqlalchemy import text  # noqa: E402

from app.core.db import SessionLocal  # noqa: E402

INGEST_EMAIL = "ingest@jobrec.local"
# `uid = NULL` evaluates to NULL (never true), so a missing account still
# cleans any stray non-native rows.
JOB_WHERE = "posted_by_user_id = :uid OR source <> 'native'"


def _count(db, sql: str, **params) -> int:
    return int(db.execute(text(sql), params).scalar() or 0)


def main() -> int:
    db = SessionLocal()
    try:
        ingest_id = db.execute(
            text("SELECT id FROM users WHERE email = :email"), {"email": INGEST_EMAIL}
        ).scalar()

        jobs = _count(db, f"SELECT count(*) FROM jobs WHERE {JOB_WHERE}", uid=ingest_id)
        db.execute(text(f"DELETE FROM jobs WHERE {JOB_WHERE}"), {"uid": ingest_id})

        companies = users = 0
        if ingest_id is not None:
            companies = _count(
                db,
                "SELECT count(*) FROM companies WHERE created_by_user_id = :uid",
                uid=ingest_id,
            )
            db.execute(
                text("DELETE FROM companies WHERE created_by_user_id = :uid"),
                {"uid": ingest_id},
            )
            users = _count(
                db, "SELECT count(*) FROM users WHERE id = :uid", uid=ingest_id
            )
            db.execute(text("DELETE FROM users WHERE id = :uid"), {"uid": ingest_id})

        db.commit()

        leftover = _count(db, "SELECT count(*) FROM jobs WHERE source <> 'native'")
        native = _count(db, "SELECT count(*) FROM jobs WHERE source = 'native'")
        employers = _count(db, "SELECT count(*) FROM users WHERE role = 'EMPLOYER'")
        seekers = _count(db, "SELECT count(*) FROM users WHERE role = 'JOB_SEEKER'")
        print(f"purged: jobs={jobs} companies={companies} users={users}")
        print(f"remaining: native_jobs={native} non_native_jobs={leftover} "
              f"employers={employers} seekers={seekers}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
