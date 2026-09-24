#!/usr/bin/env python
"""Dataset builder for M2/M3 (plan §6 M2, §21 temporal split).

Reads interactions + feedback + applications, aggregates graded labels per
(profile, job) with max semantics, rebuilds the exact serving-time feature
vector (scoring → build_features) for each row, and writes:

    ml/datasets/train.jsonl    rows with t < cutoff  (profile-grouped)
    ml/datasets/test.jsonl     rows with t ≥ cutoff
    ml/datasets/manifest.json  counts, split time, feature order, label histogram

Labels (plan §6/§16 scale): view=1 click=2 save=4 apply/shortlist-entry=6
shortlisted/relevant=8 interview=9 offer=10 negative=0.
Rows are written group-contiguous (by profile) as LightGBM requires.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

DATASETS = BACKEND_ROOT / "ml" / "datasets"

EVENT_LABELS = {"VIEW": 1, "CLICK": 2, "SAVE": 4, "APPLY": 6, "DISMISS": 0}
EVENT_LABELS_UNCHANGED = {"IGNORE": None}
APP_LABELS = {"APPLIED": 6, "VIEWED": 2, "SAVED": 4, "SHORTLISTED": 8,
              "INTERVIEW": 9, "OFFER": 10, "REJECTED": 6}
FEEDBACK_LABELS = {"RELEVANT": 8, "ALREADY_APPLIED": 6, "NOT_RELEVANT": 0,
                   "NOT_INTERESTED": 0, "TOO_DIFFICULT": 0,
                   "LOCATION_ISSUE": 0, "SALARY_ISSUE": 0, "OTHER": None}


def collect_aggregates(db) -> dict[tuple[str, str], tuple[int, datetime]]:
    """(profile_id, job_id) → (max label, latest t) across all event sources."""
    from sqlalchemy import select  # noqa: PLC0415
    from sqlalchemy.orm import selectinload  # noqa: PLC0415

    from app.models.application import Application  # noqa: PLC0415
    from app.models.feedback import Feedback  # noqa: PLC0415
    from app.models.interaction import Interaction  # noqa: PLC0415
    from app.models.job import Job  # noqa: PLC0415
    from app.models.profile import Profile  # noqa: PLC0415

    profiles = list(db.scalars(select(Profile)).all())
    profile_by_user = {str(p.user_id): p for p in profiles}
    profile_ids = {str(p.id) for p in profiles}
    if not profiles:
        return {}

    agg: dict[tuple[str, str], tuple[int, datetime]] = {}

    def _offer(pid: str, jid: str, label: int | None, ts: datetime | None) -> None:
        if label is None or ts is None:
            return
        key = (pid, jid)
        prev = agg.get(key)
        if prev is None or label > prev[0] or (label == prev[0] and ts > prev[1]):
            agg[key] = (max(label, prev[0] if prev else label),
                        max(ts, prev[1]) if prev else ts)

    for row in db.scalars(select(Interaction)).all():
        profile = profile_by_user.get(str(row.user_id))
        if profile is None:
            continue
        _offer(str(profile.id), str(row.job_id),
               EVENT_LABELS.get(row.event_type.name), row.created_at)

    for row in db.scalars(select(Feedback)).all():
        pid = str(row.profile_id)
        if pid not in profile_ids:
            continue
        _offer(pid, str(row.job_id), FEEDBACK_LABELS.get(row.reason.name),
               row.created_at)

    for row in db.scalars(
        select(Application).options(selectinload(Application.job)).where(
            Application.profile_id.in_(list(profile_ids))
        )
    ).all():
        _offer(str(row.profile_id), str(row.job_id),
               APP_LABELS.get(row.status.name),
               row.applied_at or row.updated_at)

    # drop rows whose job vanished
    jobs = {str(j.id) for j in db.scalars(select(Job)).all()}
    return {k: v for k, v in agg.items() if k[1] in jobs}


def build_feature_rows(db, agg: dict) -> list[dict]:
    """Recompute the serving-time feature vector for every (profile, job)."""
    from sqlalchemy import select  # noqa: PLC0415
    from sqlalchemy.orm import selectinload  # noqa: PLC0415

    from app.models.job import Job  # noqa: PLC0415
    from app.models.profile import Profile  # noqa: PLC0415
    from app.models.skill import JobSkill, ProfileSkill  # noqa: PLC0415
    from app.services.recommender import (
        ContentRecommender,
        _ProfileContext,
        _apply_rate,
    )
    from app.services.rerank import FEATURE_ORDER, FeatureContext, build_features
    from app.services.scoring import score_pair

    by_profile: dict[str, list[tuple[str, int, datetime]]] = defaultdict(list)
    for (pid, jid), (label, ts) in agg.items():
        by_profile[pid].append((jid, label, ts))

    if not by_profile:
        return []

    profiles = {
        str(p.id): p
        for p in db.scalars(
            select(Profile)
            .where(Profile.id.in_([pid for pid in by_profile]))
            .options(
                selectinload(Profile.skills).selectinload(ProfileSkill.skill),
                selectinload(Profile.project_rows),
                selectinload(Profile.target_family),
            )
        ).all()
    }
    needed_job_ids = {jid for rows in by_profile.values() for jid, _, _ in rows}
    jobs = {
        str(j.id): j
        for j in db.scalars(
            select(Job)
            .where(Job.id.in_(list(needed_job_ids)))
            .options(
                selectinload(Job.skills).selectinload(JobSkill.skill),
                selectinload(Job.family),
                selectinload(Job.company),
                selectinload(Job.applications),
            )
        ).all()
    }

    rows: list[dict] = []
    for pid, entries in by_profile.items():
        profile = profiles.get(pid)
        if profile is None:
            continue
        completeness = ContentRecommender.compute_profile_completeness(profile)
        try:
            ctx = _ProfileContext(profile)
        except Exception as exc:  # noqa: BLE001
            print(f"[datasets] profile {pid} context failed: {exc}", file=sys.stderr)
            continue

        for jid, label, ts in entries:
            job = jobs.get(jid)
            if job is None:
                continue
            inputs = ctx.inputs_for(job)
            result = score_pair(inputs)
            created = job.created_at
            age = 0.0
            if created is not None:
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
                age = max(0.0, (ts - created).total_seconds() / 86400.0)
            applicants = float(len(job.applications or []))
            features = build_features(
                inputs,
                result,
                FeatureContext(
                    job_age_days=age,
                    applicant_count=applicants,
                    profile_completeness=completeness,
                    historical_apply_rate=_apply_rate(job),
                    exploration_flag=0.0,
                ),
            )
            rows.append({
                "profile_id": pid,
                "job_id": jid,
                "label": int(label),
                "t": ts.isoformat(),
                "score": float(result.final),
                "features": features,
            })
            assert len(features) == len(FEATURE_ORDER)
    return rows


def temporal_split(rows: list[dict]) -> tuple[list[dict], list[dict], dict]:
    """Group-level temporal split: profiles with max(t) < cutoff → train."""
    max_t: dict[str, str] = {}
    for row in rows:
        pid = row["profile_id"]
        if pid not in max_t or row["t"] > max_t[pid]:
            max_t[pid] = row["t"]
    order = sorted(max_t.items(), key=lambda kv: (kv[1], kv[0]))
    cutoff_idx = max(1, int(len(order) * 0.8)) if len(order) > 4 else max(1, len(order) - 1)
    cutoff = order[min(cutoff_idx, len(order) - 1)][1]

    train = [r for r in rows if max_t[r["profile_id"]] < cutoff]
    test = [r for r in rows if max_t[r["profile_id"]] >= cutoff]
    info = {
        "strategy": "temporal_group",
        "cutoff": cutoff,
        "train_groups": len({r["profile_id"] for r in train}),
        "test_groups": len({r["profile_id"] for r in test}),
        "degenerate": len({v for v in max_t.values()}) <= 1,
    }
    if not train or not test:
        # fall back to a deterministic 80/20 group split so training always works
        info["strategy"] = "group_random_fallback"
        cut = max(1, int(len(order) * 0.8))
        train_ids = {pid for pid, _ in order[:cut]}
        train = [r for r in rows if r["profile_id"] in train_ids]
        test = [r for r in rows if r["profile_id"] not in train_ids]
        info["cutoff"] = order[min(cut, len(order) - 1)][1]
    return train, test, info


def _group_contiguous(rows: list[dict]) -> list[dict]:
    return sorted(rows, key=lambda r: (r["profile_id"], r["t"], r["job_id"]))


def _write(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def run(out_dir: Path = DATASETS) -> dict:
    from sqlalchemy import select  # noqa: PLC0415

    from app.core.db import SessionLocal  # noqa: PLC0415

    db = SessionLocal()
    try:
        agg = collect_aggregates(db)
        bootstrap = not agg
        rows = build_feature_rows(db, agg) if not bootstrap else []
    finally:
        db.close()

    if bootstrap:
        print("[datasets] no interaction rows found — run "
              "scripts/seed_synthetic_users.py first", file=sys.stderr)
        raise SystemExit(3)

    train_rows, test_rows, split = temporal_split(rows)
    train_rows = _group_contiguous(train_rows)
    test_rows = _group_contiguous(test_rows)

    out_dir.mkdir(parents=True, exist_ok=True)
    _write(out_dir / "train.jsonl", train_rows)
    _write(out_dir / "test.jsonl", test_rows)

    from app.services.rerank import FEATURE_ORDER  # noqa: PLC0415

    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "total_rows": len(rows),
        "train_rows": len(train_rows),
        "test_rows": len(test_rows),
        "split": split,
        "feature_order": FEATURE_ORDER,
        "label_histogram": dict(Counter(r["label"] for r in rows)),
        "groups": len({r["profile_id"] for r in rows}),
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    print(json.dumps(manifest, indent=2))
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build M2/M3 datasets")
    parser.add_argument("--out", default=str(DATASETS))
    args = parser.parse_args(argv)
    run(Path(args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
