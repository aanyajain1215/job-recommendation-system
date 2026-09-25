"""Backfill: Adzuna /in/ postings stored as USD are actually INR.

Adzuna responses omit a currency field — values arrive in the endpoint
country's currency — and the ingestion pipeline used to default to USD.
This idempotent backfill only touches rows written before the fix
(fetch_jobs_live now resolves the country-implied currency at parse time).

Revision ID: 0012_adzuna_currency_backfill
Revises: 0011_ops
Create Date: 2026-09-25
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0012_adzuna_currency_backfill"
down_revision: str | None = "0011_ops"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "UPDATE jobs SET salary_currency = 'INR' "
        "WHERE source = 'adzuna' AND salary_currency = 'USD'"
    )


def downgrade() -> None:
    # Not reversible: the pre-fix rows carried an incorrect label, and the
    # true original value (USD vs INR) cannot be distinguished from it.
    pass
