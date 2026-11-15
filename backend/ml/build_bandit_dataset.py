#!/usr/bin/env python
"""Build an offline bandit dataset from served recommendation snapshots + outcomes.

Joins recommendations that carry bandit metadata with the latest feedback or
interaction for the same (profile, job). Output JSONL rows include features,
logged propensity, and reward for off-policy evaluation/offline training.

Requires DATABASE_URL and populated tables.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build bandit dataset from DB logs")
    parser.add_argument("--out", default=str(BACKEND_ROOT / "ml" / "datasets" / "bandit_logged.jsonl"))
    parser.add_argument("--limit", type=int, default=5000)
    args = parser.parse_args(argv)

    from sqlalchemy import select
    from app.core.db import SessionLocal
    from app.models.feedback import Feedback
    from app.models.interaction import Interaction
    from app.models.profile import Profile
    from app.models.recommendation import Recommendation
    from app.services.bandit import reward_for_event, reward_for_reason

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    rows_written = 0

    with SessionLocal() as db, out.open("w", encoding="utf-8") as f:
        recs = db.scalars(
            select(Recommendation).order_by(Recommendation.served_at.desc()).limit(args.limit)
        ).all()
        for rec in recs:
            snap = rec.snapshot or {}
            b = snap.get("bandit")
            if not b or not b.get("features"):
                continue
            profile = db.get(Profile, rec.profile_id)
            if profile is None:
                continue

            reward = None
            fb = db.scalar(
                select(Feedback)
                .where(Feedback.profile_id == rec.profile_id, Feedback.job_id == rec.job_id)
                .order_by(Feedback.created_at.desc())
            )
            if fb is not None:
                val = fb.reason.value if hasattr(fb.reason, "value") else fb.reason
                reward = reward_for_reason(val)
            if reward is None:
                inter = db.scalar(
                    select(Interaction)
                    .where(Interaction.user_id == profile.user_id, Interaction.job_id == rec.job_id)
                    .order_by(Interaction.created_at.desc())
                )
                if inter is not None:
                    val = inter.event_type.value if hasattr(inter.event_type, "value") else inter.event_type
                    reward = reward_for_event(val)
            if reward is None:
                continue

            row = {
                "profile_id": str(rec.profile_id),
                "job_id": str(rec.job_id),
                "features": b.get("features"),
                "propensity": float(b.get("propensity") or snap.get("propensity") or 1.0),
                "reward": float(reward),
                "policy": b.get("policy"),
                "model_version": b.get("model_version"),
                "served_at": rec.served_at.isoformat() if rec.served_at else None,
            }
            f.write(json.dumps(row) + "\n")
            rows_written += 1

    print(json.dumps({"out": str(out), "rows": rows_written}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
