#!/usr/bin/env python
"""Build (resume/profile text, job description text) pairs for M0 fine-tuning.

Hygiene rules (leak-free, label-clean):
  - Positives (label=1): strong intent/outcome signals only:
      APPLIED, SHORTLISTED, INTERVIEW, OFFER, SAVED (applications),
      RELEVANT, ALREADY_APPLIED (explicit feedback),
      APPLY, SAVE (high-intent interactions).
    Passive views/clicks are excluded (no VIEWED, no CLICK).
  - Negatives (label=0): explicit dismissals/negative feedback:
      DISMISS (interaction), NOT_RELEVANT, NOT_INTERESTED, TOO_DIFFICULT,
      LOCATION_ISSUE, SALARY_ISSUE (feedback).

Pairs are exported as JSONL for bi-encoder (MNRL/InfoNCE) and cross-encoder
training. `profile_id` and `job_id` are included so downstream scripts can do
strict group-by-user (zero user overlap) train/validation splitting.

Output: ml/datasets/embedding_pairs.jsonl
Each row: {"profile_id", "job_id", "profile_text", "job_text", "label", "source"}
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

OUT = BACKEND_ROOT / "ml" / "datasets" / "embedding_pairs.jsonl"

# Strong positive signals only (no passive VIEWED)
POS_APP = {"APPLIED", "SHORTLISTED", "INTERVIEW", "OFFER", "SAVED"}
POS_FEEDBACK = {"RELEVANT", "ALREADY_APPLIED"}
# High-intent interactions only (no passive CLICK)
POS_EVENT = {"APPLY", "SAVE"}
NEG_FEEDBACK = {"NOT_RELEVANT", "NOT_INTERESTED", "TOO_DIFFICULT", "LOCATION_ISSUE", "SALARY_ISSUE"}


def _profile_text(profile) -> str:
    parts = []
    for p in (getattr(profile, "headline", None), getattr(profile, "bio", None), getattr(profile, "raw_resume_text", None)):
        if p:
            parts.append(str(p))
    # parsed resume data skills summary if available
    parsed = getattr(profile, "parsed_resume_data", None) or {}
    try:
        skills = parsed.get("skills") or parsed.get("autofill", {}).get("skills") or []
        if skills:
            names = []
            for s in skills:
                if isinstance(s, dict):
                    names.append(str(s.get("name") or s.get("skill") or ""))
                else:
                    names.append(str(s))
            names = [n for n in names if n]
            if names:
                parts.append("Skills: " + ", ".join(names[:60]))
    except Exception:
        pass
    try:
        skill_rows = getattr(profile, "skills", None) or []
        names = [ps.skill.name for ps in skill_rows if getattr(ps, "skill", None) and ps.skill.name]
        if names:
            parts.append("Profile skills: " + ", ".join(names[:60]))
    except Exception:
        pass
    return "\n".join(parts).strip()


def _job_text(job) -> str:
    parts = [str(getattr(job, "title", "") or "")]
    for p in (getattr(job, "requirements", None), getattr(job, "description", None)):
        if p:
            parts.append(str(p))
    try:
        names = [js.skill.name for js in (job.skills or []) if getattr(js, "skill", None) and js.skill.name]
        if names:
            parts.append("Required skills: " + ", ".join(names[:60]))
    except Exception:
        pass
    return "\n".join(parts).strip()


def build() -> list[dict]:
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.core.db import SessionLocal
    from app.models.application import Application
    from app.models.feedback import Feedback
    from app.models.interaction import Interaction
    from app.models.job import Job
    from app.models.profile import Profile
    from app.models.skill import JobSkill, ProfileSkill

    db = SessionLocal()
    try:
        profiles = {
            str(p.id): p
            for p in db.scalars(
                select(Profile).options(
                    selectinload(Profile.skills).selectinload(ProfileSkill.skill)
                )
            ).all()
        }
        profiles_by_user = {str(p.user_id): p for p in profiles.values()}
        jobs = {
            str(j.id): j
            for j in db.scalars(
                select(Job).options(selectinload(Job.skills).selectinload(JobSkill.skill))
            ).all()
        }

        pair_labels: dict[tuple[str, str], tuple[int, str]] = {}

        def set_pair(pid: str, jid: str, label: int, source: str):
            if pid not in profiles or jid not in jobs:
                return
            key = (pid, jid)
            prev = pair_labels.get(key)
            # prefer positive over negative if conflicting, and keep strongest label
            if prev is None or label > prev[0]:
                pair_labels[key] = (label, source)

        for row in db.scalars(select(Interaction)).all():
            p = profiles_by_user.get(str(row.user_id))
            if not p:
                continue
            ev = row.event_type.name
            if ev in POS_EVENT:
                set_pair(str(p.id), str(row.job_id), 1, f"interaction:{ev}")
            elif ev == "DISMISS":
                set_pair(str(p.id), str(row.job_id), 0, f"interaction:{ev}")
            # passive events (e.g. VIEW/CLICK if present) intentionally ignored

        for row in db.scalars(select(Feedback)).all():
            reason = row.reason.name
            if reason in POS_FEEDBACK:
                set_pair(str(row.profile_id), str(row.job_id), 1, f"feedback:{reason}")
            elif reason in NEG_FEEDBACK:
                set_pair(str(row.profile_id), str(row.job_id), 0, f"feedback:{reason}")

        for row in db.scalars(select(Application)).all():
            st = row.status.name
            if st in POS_APP:
                set_pair(str(row.profile_id), str(row.job_id), 1, f"application:{st}")
            # non-strong statuses ignored; explicit negative feedback handled above

        rows = []
        for (pid, jid), (label, source) in pair_labels.items():
            pt = _profile_text(profiles[pid])
            jt = _job_text(jobs[jid])
            if not pt or not jt:
                continue
            rows.append(
                {
                    "profile_id": pid,
                    "job_id": jid,
                    "profile_text": pt[:4000],
                    "job_text": jt[:4000],
                    "label": int(label),
                    "source": source,
                }
            )
        return rows
    finally:
        db.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build M0 embedding training pairs")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args(argv)
    rows = build()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    pos = sum(1 for r in rows if r["label"] == 1)
    neg = sum(1 for r in rows if r["label"] == 0)
    print(json.dumps({"out": str(out), "rows": len(rows), "positives": pos, "negatives": neg}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
