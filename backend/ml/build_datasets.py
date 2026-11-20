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
    agg = {k: v for k, v in agg.items() if k[1] in jobs}

    # Bootstrap/supplement: ensure ranking groups are learnable and evaluation-valid.
    # - every profile gets a minimum group size
    # - every user with positive interactions gets sampled hard-negative postings
    #   (label-0 unseen jobs) for contrastive learning and IR evaluation.
    if agg and jobs:
        import random as _random  # noqa: PLC0415

        job_ids = list(jobs)
        all_profiles = [str(p.id) for p in profiles]
        rng_seed = sum(ord(c) for p in all_profiles for c in p[:8]) % 9973
        _rng = _random.Random(rng_seed)
        POS_MIN = 4  # high-intent positive threshold
        MIN_GROUP = 4
        MIN_NEG_FOR_POS_USERS = 3

        def _add_negatives(pid: str, need: int):
            if need <= 0:
                return
            candidates = [j for j in job_ids if (pid, j) not in agg]
            _rng.shuffle(candidates)
            for jid in candidates[:need]:
                agg[(pid, jid)] = (0, datetime.now(timezone.utc))

        for pid in all_profiles:
            existing_keys = [(p, jid) for (p, jid) in agg.keys() if p == pid]
            labels = [agg[k][0] for k in existing_keys]
            has_pos = any(int(l) >= POS_MIN for l in labels)
            neg_count = sum(1 for l in labels if int(l) == 0)

            # ensure minimum group size
            if len(existing_keys) < MIN_GROUP:
                _add_negatives(pid, MIN_GROUP - len(existing_keys))
                existing_keys = [(p, jid) for (p, jid) in agg.keys() if p == pid]
                labels = [agg[k][0] for k in existing_keys]
                neg_count = sum(1 for l in labels if int(l) == 0)

            # ensure positive-bearing users have hard negatives for contrast
            if has_pos and neg_count < MIN_NEG_FOR_POS_USERS:
                _add_negatives(pid, MIN_NEG_FOR_POS_USERS - neg_count)

    return agg


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

    # optional CE scoring (M0) for richer semantic features
    ce_scorer = None
    try:
        from app.services.cross_encoder import get_cross_encoder  # noqa: PLC0415
        ce_scorer = get_cross_encoder()
    except Exception:
        ce_scorer = None

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

        # prepare per-job feature inputs first
        per_job = []
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
            per_job.append((jid, job, label, ts, inputs, result, age, applicants))

        ce_logits_map: dict[str, float] = {}
        ce_probs_map: dict[str, float] = {}
        if ce_scorer is not None and per_job:
            try:
                pairs = [(getattr(profile, "resume_text", "") or "", getattr(job, "description", "") or "") for _, job, *_ in per_job]
                if hasattr(ce_scorer, "score_pairs_detailed"):
                    # returns (logits, probs) arrays - previously this was read as a
                    # list of dicts, which raised and silently zeroed both features
                    logits, probs = ce_scorer.score_pairs_detailed(pairs)
                    for (jid, *_rest), lg, pr in zip(per_job, logits, probs):
                        ce_logits_map[jid] = float(lg)
                        ce_probs_map[jid] = float(pr)
                else:
                    probs = ce_scorer.score_pairs(pairs)
                    for (jid, *_rest), p in zip(per_job, probs):
                        ce_probs_map[jid] = float(p)
            except Exception as exc:  # noqa: BLE001
                print(f"[datasets] cross-encoder scoring failed for profile {pid}: {exc}", file=sys.stderr)

        for jid, _job, label, ts, inputs, result, age, applicants in per_job:
            features = build_features(
                inputs,
                result,
                FeatureContext(
                    job_age_days=age,
                    applicant_count=applicants,
                    profile_completeness=completeness,
                    historical_apply_rate=_apply_rate(_job),
                    exploration_flag=0.0,
                    cross_encoder_logit=ce_logits_map.get(jid, 0.0),
                    cross_encoder_prob=ce_probs_map.get(jid, 0.0),
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
    """Strict profile-level split (80/20 by profile_id, zero user overlap).

    Profiles are shuffled deterministically by hash of profile_id so the split is
    stable and group-pure (all rows for a profile stay in the same fold). Real
    interaction/application/feedback labels are preserved.
    """
    import hashlib  # noqa: PLC0415

    profile_ids = sorted({r["profile_id"] for r in rows})
    def _key(pid: str) -> str:
        return hashlib.sha256(pid.encode("utf-8")).hexdigest()

    ordered = sorted(profile_ids, key=_key)
    cut = max(1, int(len(ordered) * 0.8))
    if cut >= len(ordered) and len(ordered) > 1:
        cut = len(ordered) - 1
    train_ids = set(ordered[:cut])
    test_ids = set(ordered[cut:])

    train = [r for r in rows if r["profile_id"] in train_ids]
    test = [r for r in rows if r["profile_id"] in test_ids]
    info = {
        "strategy": "profile_id_hash_80_20",
        "cutoff": None,
        "train_groups": len(train_ids),
        "test_groups": len(test_ids),
        "degenerate": False,
        "zero_user_overlap": True,
    }
    # safety fallback (should be rare)
    if (not train or not test) and profile_ids:
        cut = max(1, int(len(ordered) * 0.8))
        train_ids = set(ordered[:cut])
        train = [r for r in rows if r["profile_id"] in train_ids]
        test = [r for r in rows if r["profile_id"] not in train_ids]
        info["strategy"] = "profile_id_fallback_80_20"
        info["train_groups"] = len({r["profile_id"] for r in train})
        info["test_groups"] = len({r["profile_id"] for r in test})
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
        print("[datasets] no interaction rows found - run scripts/seed_synthetic_users.py first", file=sys.stderr)
        return 3

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
    try:
        res = run(Path(args.out))
        if isinstance(res, int):
            return res
        return 0
    except SystemExit as e:
        code = e.code
        if code is None:
            return 0
        if isinstance(code, int):
            return code
        return 1
    except Exception as exc:
        print(f"[datasets] error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
