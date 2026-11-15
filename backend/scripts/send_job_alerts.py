#!/usr/bin/env python
"""Job-alert digest worker.

Finds newly published jobs that resemble the jobs a seeker has saved
(``applications.status = 'saved'``), then delivers one digest per due user as
in-app notifications plus an optional email.

Usage:
    cd backend
    python scripts/send_job_alerts.py                 # one pass, all users
    python scripts/send_job_alerts.py --dry-run       # print matches, write nothing
    python scripts/send_job_alerts.py --user-id <uuid>
    python scripts/send_job_alerts.py --force         # ignore cadence
    python scripts/send_job_alerts.py --no-email      # in-app only
    python scripts/send_job_alerts.py --loop          # run forever (Compose)

In-app notifications are always created when ``ALERTS_ENABLED`` is true;
email is only attempted when ``EMAIL_ALERTS_ENABLED`` is true *and* SMTP is
configured, so in-app alerts keep working with no mail server at all.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from uuid import UUID

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core.config import get_settings  # noqa: E402
from app.core.db import SessionLocal  # noqa: E402
from app.services.job_alerts import run_alert_cycle  # noqa: E402

log = logging.getLogger("send_job_alerts")


def _parse_uuid(value: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as exc:  # pragma: no cover - argparse surface
        raise argparse.ArgumentTypeError(f"invalid UUID: {value}") from exc


def run_once(args: argparse.Namespace) -> dict:
    settings = get_settings()
    with SessionLocal() as db:
        result = run_alert_cycle(
            db,
            dry_run=args.dry_run,
            force=args.force,
            email_enabled=False if args.no_email else None,
            user_id=args.user_id,
        )
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        mode = "dry-run" if result.get("dry_run") else "live"
        log.info(
            "%s: users=%s digests=%s items=%s emails_sent=%s emails_failed=%s",
            mode,
            result.get("users_scanned"),
            result.get("digests_sent"),
            result.get("items_sent"),
            result.get("emails_sent"),
            result.get("emails_failed"),
        )
        if not result.get("enabled"):
            log.info("alerts disabled (ALERTS_ENABLED=false); nothing to do")
        for row in result.get("results", []):
            if result.get("dry_run") or row.get("status") == "sent":
                log.info(
                    "  user=%s status=%s items=%s",
                    row.get("user_id"),
                    row.get("status"),
                    row.get("items"),
                )
                for item in row.get("items", []) if isinstance(row.get("items"), list) else []:
                    log.info(
                        "    %.1f%% %s (seed: %s)",
                        item.get("score", 0.0),
                        item.get("title"),
                        item.get("seed_job_id"),
                    )
                for title in row.get("titles", []):
                    log.info("    %s", title)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="match only, write nothing")
    parser.add_argument("--user-id", type=_parse_uuid, default=None, help="scope to one user")
    parser.add_argument("--force", action="store_true", help="ignore digest cadence")
    parser.add_argument("--no-email", action="store_true", help="skip email delivery")
    parser.add_argument("--loop", action="store_true", help="run forever on a timer")
    parser.add_argument(
        "--interval",
        type=int,
        default=None,
        help="seconds between passes in --loop mode (default: ALERT_INTERVAL_SECONDS)",
    )
    parser.add_argument("--json", action="store_true", help="print the run report as JSON")
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    if not args.loop:
        run_once(args)
        return 0

    settings = get_settings()
    interval = args.interval or settings.alert_interval_seconds
    interval = max(60, int(interval))
    log.info("alert worker loop started; interval=%ss", interval)
    while True:
        try:
            run_once(args)
        except Exception:  # noqa: BLE001 - a failed pass must not kill the worker
            log.exception("alert cycle failed; retrying next interval")
        time.sleep(interval)


if __name__ == "__main__":
    raise SystemExit(main())
