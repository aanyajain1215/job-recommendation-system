#!/usr/bin/env python
"""M2 ranker dataset from REAL job applications (CareerBuilder, Kaggle 2012).

Replaces the synthetic labels from ml/ground_truth.py (heuristic score + noise)
with what real people actually applied to.

Source: Kaggle "Job Recommendation Challenge" (CareerBuilder.com, 2012), files
in ml/data/external/careerbuilder/ (git-ignored; competition rules apply).
  users.tsv / user_history.tsv  seekers: location, degree, major, years, past titles
  apps.tsv                      1.6M real applications (user -> job, timestamp)
  jobs.tsv (3.4 GB, streamed)   postings: title, HTML description/requirements, location

Scope: tech jobs only (job title matches a family in families.yaml, the app's
domain): ~24k postings, ~9.7k applications, ~6.4k users.

Groups   one ranking group per user (each user belongs to exactly one window).
Labels   applied = 6 (APPLY on the app's scale); not applied = 0.
Negatives per user: tech jobs from the same window the user did NOT apply to -
         mostly from the user's own state (realistic local search), plus some
         from anywhere.
Split    by time window: 1-5 train, 6 validation, 7 test (no user overlap).

Every feature is computed with the app's own serving code so train == serve:
skill extraction, seniority, job family, the bi-encoder embedder, the fine-tuned
cross-encoder, the O*NET skill graph (transfer), score_pair (heuristic baseline,
stored as `score`) and rerank.build_features (31 features).

Deliberate gaps (kept identical to what serving sees, documented in manifest):
  education      serving passes no degree bar -> left empty here too
  salary         not in the data
  applicant_count / historical_apply_rate   0 (live Adzuna jobs have no
                 platform applications; CB counts would also leak the label)

Expensive stages are cached in backend/.cache/careerbuilder/ in chunks, so a
crash resumes where it stopped.  CPU only.
"""

from __future__ import annotations

import os

os.environ.setdefault("CUDA_VISIBLE_DEVICES", "-1")  # CPU only (laptop GPU unstable)
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://unused:unused@localhost:1/unused")

import argparse  # noqa: E402
import csv  # noqa: E402
import hashlib  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import random  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
import zipfile  # noqa: E402
from collections import Counter, defaultdict  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from ml.resume_jd_fit import CACHE_ROOT, use_project_cache  # noqa: E402

use_project_cache()
csv.field_size_limit(10**9)

RAW = BACKEND_ROOT / "ml" / "data" / "external" / "careerbuilder"
CACHE = CACHE_ROOT / "careerbuilder"
OUT = BACKEND_ROOT / "ml" / "datasets" / "careerbuilder"
LABEL_APPLY = 6
TRAIN_WINDOWS, VAL_WINDOWS, TEST_WINDOWS = {1, 2, 3, 4, 5}, {6}, {7}


def log(msg: str) -> None:
    print(f"[cb {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _tsv_rows(zip_name: str, member: str):
    with zipfile.ZipFile(RAW / zip_name) as z, z.open(member) as fh:
        reader = csv.reader(io.TextIOWrapper(fh, encoding="utf-8", errors="replace"),
                            delimiter="\t", quoting=csv.QUOTE_NONE)
        header = next(reader)
        for row in reader:
            if len(row) == len(header):
                yield dict(zip(header, row))


def _parse_dt(text: str) -> datetime | None:
    text = (text or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


# --------------------------------------------------------------------------
# Stage 1: tech jobs (streamed from the 3.4 GB TSV, parsed with app code)
# --------------------------------------------------------------------------

def load_tech_jobs() -> dict[str, dict]:
    path = CACHE / "tech_jobs.jsonl"
    if path.exists():
        return {j["id"]: j for j in map(json.loads, path.read_text(encoding="utf-8").splitlines())}
    from app.services.ingest import (  # noqa: PLC0415
        assign_family, clean_text, detect_remote, extract_skills, load_families,
        load_surface_pairs, map_seniority, parse_years,
    )

    fams, pairs = load_families(), load_surface_pairs()
    jobs: dict[str, dict] = {}
    t0 = time.time()
    with zipfile.ZipFile(RAW / "jobs.zip") as z, z.open("jobs.tsv") as fh:
        for i, line in enumerate(io.TextIOWrapper(fh, encoding="utf-8", errors="replace")):
            if i == 0:
                continue
            p = line.rstrip("\n").split("\t")
            if len(p) < 11:
                continue
            family = assign_family(p[2], fams)
            if not family:
                continue
            title = clean_text(p[2])
            desc = clean_text(p[3].replace("\\r", "\n").replace("\\n", "\n"))[:4000]
            req = clean_text(p[4].replace("\\r", "\n").replace("\\n", "\n"))[:2000]
            city, state = p[5].strip(), p[6].strip()
            location = ", ".join(x for x in (city, state) if x) or None
            jobs[p[0]] = {
                "id": p[0], "window": int(p[1]), "title": title, "description": desc,
                "requirements": req, "location": location, "state": state,
                "start": p[9].strip(), "family": family,
                "level": map_seniority(title, parse_years(f"{req}\n{desc}")).value,
                "remote": detect_remote(title, desc, location),
                "skills": extract_skills(title, f"{req}\n{desc}", pairs),
            }
    CACHE.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(j) for j in jobs.values()), encoding="utf-8")
    log(f"stage 1: {len(jobs)} tech jobs parsed in {time.time() - t0:.0f}s")
    return jobs


# --------------------------------------------------------------------------
# Stage 2: users, history, applications -> groups with sampled negatives
# --------------------------------------------------------------------------

def build_groups(jobs: dict[str, dict], negatives: int, same_state: int, seed: int,
                 prefer: set[str] | None = None) -> list[dict]:
    """One group per user: applied tech jobs (positives) + sampled negatives.

    Negatives must be jobs the user could have seen: same window AND already
    posted at the user's reference (median application) time. A first version
    skipped that check and also mis-parsed the negatives' reference date, so
    every negative got job_age_days = 0 - a label leak the model exploited
    (99% of LightGBM gain on job_age_days). `prefer` (already-embedded jobs) is
    used for top-ups so cached embeddings are reused; it covers ~85% of jobs.
    """
    apps = defaultdict(list)
    for r in _tsv_rows("apps.zip", "apps.tsv"):
        if r["JobID"] in jobs:
            apps[r["UserID"]].append((r["JobID"], r["ApplicationDate"], int(r["WindowID"])))
    users = {r["UserID"]: r for r in _tsv_rows("users.zip", "users.tsv") if r["UserID"] in apps}
    history = defaultdict(list)
    for r in _tsv_rows("user_history.zip", "user_history.tsv"):
        if r["UserID"] in users:
            history[r["UserID"]].append((int(r["Sequence"] or 0), r["JobTitle"].strip()))

    by_window = defaultdict(list)
    by_window_state = defaultdict(list)
    for j in jobs.values():
        by_window[j["window"]].append(j["id"])
        by_window_state[(j["window"], j["state"])].append(j["id"])
    start_dt = {jid: _parse_dt(j["start"]) for jid, j in jobs.items()}

    rng = random.Random(seed)
    groups = []
    stats = Counter()
    for uid in sorted(apps, key=int):
        u = users.get(uid)
        if u is None:
            continue
        window = int(u["WindowID"])
        applied = {}
        for jid, date, _w in apps[uid]:
            applied.setdefault(jid, date)
        dated = sorted((d for d in applied.values() if _parse_dt(d)), key=_parse_dt)
        ref_raw = dated[len(dated) // 2] if dated else None  # keep the raw format (parsable)
        ref_dt = _parse_dt(ref_raw) if ref_raw else None

        def posted(jid: str) -> bool:
            sd = start_dt.get(jid)
            return ref_dt is not None and sd is not None and sd <= ref_dt

        local = [j for j in by_window_state.get((window, u["State"]), []) if j not in applied]
        anywhere = [j for j in by_window.get(window, []) if j not in applied]
        # same draws as the first build (keeps cached cross-encoder pairs reusable) ...
        negs = rng.sample(local, min(same_state, len(local)))
        pool = [j for j in anywhere if j not in set(negs)]
        negs += rng.sample(pool, min(negatives - len(negs), len(pool)))
        kept_local = [j for j in negs[:same_state] if posted(j)]
        kept_any = [j for j in negs[same_state:] if posted(j)]
        stats["dropped_not_yet_posted"] += len(negs) - len(kept_local) - len(kept_any)
        # ... then top up with posted jobs (preferring already-embedded ones)
        top = random.Random(f"{seed}-{uid}")
        chosen = set(kept_local) | set(kept_any)

        def fill(cands: list[str], need: int) -> list[str]:
            ok = [j for j in cands if j not in chosen and posted(j)]
            pref = [j for j in ok if prefer is None or j in prefer]
            pick = top.sample(pref, min(need, len(pref)))
            if len(pick) < need:
                rest = [j for j in ok if j not in set(pick)]
                pick += top.sample(rest, min(need - len(pick), len(rest)))
            chosen.update(pick)
            return pick

        kept_local += fill(local, same_state - len(kept_local))
        kept_any += fill(anywhere, negatives - same_state - len(kept_any))
        final_negs = kept_local + kept_any
        stats["negatives"] += len(final_negs)
        titles = [t for _s, t in sorted(history.get(uid, [])) if t]
        groups.append({
            "user_id": uid, "window": window, "user": u, "titles": titles[:5],
            "items": [(jid, LABEL_APPLY, date) for jid, date in applied.items()]
                     + [(jid, 0, ref_raw) for jid in final_negs],
        })
    log(f"stage 2: {len(groups)} user groups, "
        f"{sum(len(g['items']) for g in groups)} (user, job) rows; {dict(stats)}")
    return groups


# --------------------------------------------------------------------------
# Profiles (CB user -> the same objects the app builds for a real profile)
# --------------------------------------------------------------------------

def make_profile(g: dict, pairs, fams) -> dict:
    from app.services.ingest import assign_family, extract_skills  # noqa: PLC0415

    u = g["user"]
    titles = g["titles"]
    headline = titles[0] if titles else None
    degree = (u.get("DegreeType") or "").strip()
    major = (u.get("Major") or "").strip()
    if major.lower() in {"not applicable", "none", "n/a"}:
        major = ""
    try:
        years = float(u.get("TotalYearsExperience") or "")
    except ValueError:
        years = None
    bio_parts = []
    if titles[1:]:
        bio_parts.append("Previous roles: " + "; ".join(titles[1:]))
    if degree and degree.lower() != "none":
        bio_parts.append(f"Education: {degree}" + (f" in {major}" if major else ""))
    if years is not None:
        bio_parts.append(f"{years:g} years of experience")
    bio = ". ".join(bio_parts) or None
    skills = [c for c, _req in extract_skills(" ".join(titles), major, pairs)]
    location = ", ".join(x for x in (u.get("City", "").strip(), u.get("State", "").strip()) if x) or None
    completeness = 15.0 + (15.0 if headline else 0) + (15.0 if bio and len(bio) > 20 else 0) \
        + (10.0 if location else 0) + (10.0 if years is not None else 0) \
        + (20.0 if len(skills) >= 5 else 10.0 if skills else 0)  # mirrors compute_profile_completeness
    return {
        "headline": headline, "bio": bio, "skills": skills, "years": years, "location": location,
        "target_family": assign_family(headline or "", fams) if headline else None,
        "completeness": completeness,
    }


# --------------------------------------------------------------------------
# Stage 3/4: embeddings + cross-encoder scores (cached, chunked, resumable)
# --------------------------------------------------------------------------

def _cache_files(prefix: str, ext: str):
    for d in sorted(CACHE.glob(f"{prefix}*")):
        if d.is_dir():
            yield from sorted(d.glob(f"*.{ext}"))


def cached_embeddings(name: str, keys: list[str], texts: list[str], chunk: int = 512) -> dict[str, np.ndarray]:
    """Key-based cache: reuse any vector computed by an earlier run (any emb_<name>* dir)."""
    from app.services.embeddings import get_embedder  # noqa: PLC0415

    known: dict[str, np.ndarray] = {}
    for f in _cache_files(f"emb_{name}", "npz"):
        z = np.load(f, allow_pickle=False)
        known.update(zip(z["keys"].tolist(), z["vecs"]))
    missing = [(k, t) for k, t in zip(keys, texts) if k not in known]
    log(f"  {name} embeddings: {len(keys) - len(missing)} cached, {len(missing)} to compute")
    d = CACHE / f"emb_{name}_extra"
    d.mkdir(parents=True, exist_ok=True)
    embedder = None
    for start in range(0, len(missing), chunk):
        part = missing[start:start + chunk]
        embedder = embedder or get_embedder()
        t0 = time.time()
        vecs = embedder.encode([t for _k, t in part])
        np.savez(d / f"{len(list(d.glob('*.npz'))):07d}.npz", keys=np.array([k for k, _t in part]), vecs=vecs)
        known.update(zip([k for k, _t in part], vecs))
        log(f"  {name} embeddings {min(start + chunk, len(missing))}/{len(missing)} ({time.time() - t0:.0f}s/chunk)")
    return {k: known[k] for k in keys}


def cached_ce(keys: list[str], pairs: list[tuple[str, str]], chunk: int = 1024) -> dict[str, tuple[float, float]]:
    """Key-based cache ("user|job"): reuse any score from an earlier run (any ce_* dir)."""
    from app.services.cross_encoder import get_cross_encoder  # noqa: PLC0415

    known: dict[str, tuple[float, float]] = {}
    for f in _cache_files("ce_", "json"):
        known.update({k: tuple(v) for k, v in json.loads(f.read_text(encoding="utf-8")).items()})
    missing = [(k, pr) for k, pr in zip(keys, pairs) if k not in known]
    log(f"  cross-encoder: {len(keys) - len(missing)} cached, {len(missing)} to score")
    d = CACHE / "ce_extra"
    d.mkdir(parents=True, exist_ok=True)
    ce = None
    for start in range(0, len(missing), chunk):
        part = missing[start:start + chunk]
        ce = ce or get_cross_encoder()
        t0 = time.time()
        logits, probs = ce.score_pairs_detailed([pr for _k, pr in part])
        scored = {k: (float(lg), float(pb)) for (k, _pr), lg, pb in zip(part, logits, probs)}
        (d / f"{len(list(d.glob('*.json'))):07d}.json").write_text(json.dumps(scored), encoding="utf-8")
        known.update(scored)
        log(f"  cross-encoder {min(start + chunk, len(missing))}/{len(missing)} ({time.time() - t0:.0f}s/chunk)")
    return {k: known[k] for k in keys}


# --------------------------------------------------------------------------
# Stage 5: features (identical to recommender._ProfileContext.inputs_for)
# --------------------------------------------------------------------------

def build_rows(groups, jobs, profiles, emb_u, emb_j, ce) -> list[dict]:
    from app.models.enums import ExperienceLevel  # noqa: PLC0415
    from app.services.ingest import load_families  # noqa: PLC0415
    from app.services.rerank import FEATURE_ORDER, FeatureContext, build_features  # noqa: PLC0415
    from app.services.scoring import ComponentInputs, JobSkillReq, score_pair  # noqa: PLC0415
    from app.services.skill_graph import load_seed_graph, transfer_similarity  # noqa: PLC0415

    parent = {f["name"]: f.get("parent") for f in load_families()}
    graph = load_seed_graph()
    rows = []
    for g in groups:
        p = profiles[g["user_id"]]
        seeker_skills = {s.lower().strip(): (None, None) for s in p["skills"]}
        possessed = set(seeker_skills)
        uvec = emb_u.get(g["user_id"])
        for jid, label, ref in g["items"]:
            j = jobs[jid]
            reqs = [JobSkillReq(name=name, is_required=bool(req)) for name, req in j["skills"]]
            transfers = {}
            for r in reqs:
                key = r.name.lower().strip()
                if key not in possessed:
                    sim = transfer_similarity(graph, possessed, r.name)
                    if sim is not None:
                        transfers[key] = sim
            jvec = emb_j.get(jid)
            cosine = float(np.dot(uvec, jvec)) if uvec is not None and jvec is not None else None
            tf, jf = p["target_family"], j["family"]
            distance = 1 if (tf and jf and tf != jf and parent.get(tf) and parent.get(tf) == parent.get(jf)) else None
            inputs = ComponentInputs(
                semantic_cosine=cosine, seeker_skills=seeker_skills, job_skills=reqs,
                transfer_similarities=transfers, years_of_experience=p["years"],
                job_level=ExperienceLevel(j["level"]),
                seeker_degree=None, seeker_field=None, job_degree=None, job_field=None,
                seeker_project_skills=set(), job_is_remote=bool(j["remote"]),
                seeker_location=p["location"], job_location=j["location"],
                seeker_preferred_locations=set(), seeker_open_to_remote=True,
                seeker_target_family=tf, job_family=jf, family_graph_distance=distance,
            )
            result = score_pair(inputs)
            start, at = _parse_dt(j["start"]), _parse_dt(ref) if ref else None
            age = max(0.0, (at - start).total_seconds() / 86400.0) if start and at else 0.0
            lg, pr = ce.get(f"{g['user_id']}|{jid}", (0.0, 0.0))
            feats = build_features(inputs, result, FeatureContext(
                job_age_days=age, applicant_count=0.0, profile_completeness=p["completeness"],
                historical_apply_rate=0.0, cross_encoder_logit=lg, cross_encoder_prob=pr))
            assert len(feats) == len(FEATURE_ORDER)
            rows.append({"profile_id": f"cb-{g['user_id']}", "job_id": f"cb-{jid}", "label": label,
                         "t": ref or "", "window": g["window"], "score": float(result.final),
                         "features": feats})
    return rows


def run(args) -> dict:
    import torch  # noqa: PLC0415
    from app.services.embeddings import build_job_text, build_profile_text  # noqa: PLC0415
    from app.services.ingest import load_families, load_surface_pairs  # noqa: PLC0415

    torch.set_num_threads(args.threads or max(1, (os.cpu_count() or 2) - 2))
    CACHE.mkdir(parents=True, exist_ok=True)
    t_start = time.time()
    jobs = load_tech_jobs()
    embedded_jobs: set[str] = set()
    for f in _cache_files("emb_jobs", "npz"):
        embedded_jobs.update(np.load(f, allow_pickle=False)["keys"].tolist())
    groups = build_groups(jobs, args.negatives, args.same_state, args.seed, prefer=embedded_jobs or None)
    if args.max_users:
        groups = random.Random(args.seed).sample(groups, min(args.max_users, len(groups)))
        groups.sort(key=lambda g: int(g["user_id"]))
    pairs, fams = load_surface_pairs(), load_families()
    profiles = {g["user_id"]: make_profile(g, pairs, fams) for g in groups}

    def ptext(p):
        return build_profile_text(p["headline"], p["bio"], p["skills"], p["target_family"]) or " "

    def jtext(j):
        req = [n for n, r in j["skills"] if r]
        return build_job_text(j["title"], j["requirements"], j["description"], req)

    used_jobs = sorted({jid for g in groups for jid, _l, _r in g["items"]}, key=int)
    tag = f"n{args.negatives}_s{args.same_state}_seed{args.seed}_u{args.max_users or 'all'}"
    log(f"embedding {len(profiles)} profiles + {len(used_jobs)} jobs (BGE, CPU)")
    emb_u = cached_embeddings("users", list(profiles), [ptext(profiles[u]) for u in profiles])
    emb_j = cached_embeddings("jobs", used_jobs, [jtext(jobs[j]) for j in used_jobs])

    keys, ce_pairs = [], []
    for g in groups:
        pt = ptext(profiles[g["user_id"]])
        for jid, _l, _r in g["items"]:
            keys.append(f"{g['user_id']}|{jid}")
            ce_pairs.append((pt, jtext(jobs[jid])))
    log(f"cross-encoder scoring {len(keys)} pairs (fine-tuned, CPU)")
    ce = cached_ce(keys, ce_pairs) if not args.skip_ce else {}

    rows = build_rows(groups, jobs, profiles, emb_u, emb_j, ce)
    # group-contiguous, but NOT label-ordered: ranking metrics break score ties by file
    # order, so positives-first rows would silently favour models that produce ties
    rows.sort(key=lambda r: (r["profile_id"], hashlib.sha1(r["job_id"].encode()).hexdigest()))
    split = {"train": [r for r in rows if r["window"] in TRAIN_WINDOWS],
             "val": [r for r in rows if r["window"] in VAL_WINDOWS],
             "test": [r for r in rows if r["window"] in TEST_WINDOWS]}
    OUT.mkdir(parents=True, exist_ok=True)
    for name, part in split.items():
        with (OUT / f"{name}.jsonl").open("w", encoding="utf-8") as fh:
            for r in part:
                fh.write(json.dumps(r) + "\n")

    from app.services.rerank import FEATURE_ORDER  # noqa: PLC0415

    X = np.array([r["features"] for r in rows], dtype=np.float32)
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": "Kaggle Job Recommendation Challenge (CareerBuilder.com, 2012) - real applications",
        "scope": "tech jobs only (title matches families.yaml)",
        "labels": {"applied": LABEL_APPLY, "not_applied_sampled": 0},
        "negatives": {"per_user": args.negatives, "same_state": args.same_state,
                      "rule": "same time window, already posted at the user's search time, not applied"},
        "split": {"train_windows": sorted(TRAIN_WINDOWS), "val_windows": sorted(VAL_WINDOWS),
                  "test_windows": sorted(TEST_WINDOWS), "user_overlap": "none (each user is in one window)"},
        "rows": {k: len(v) for k, v in split.items()},
        "groups": {k: len({r["profile_id"] for r in v}) for k, v in split.items()},
        "positives": {k: sum(r["label"] > 0 for r in v) for k, v in split.items()},
        "family_mix": dict(Counter(jobs[r["job_id"][3:]]["family"] for r in rows if r["label"] > 0)),
        "feature_order": FEATURE_ORDER,
        "constant_features": [FEATURE_ORDER[i] for i in range(X.shape[1]) if float(X[:, i].std()) == 0.0],
        "known_gaps": ["education left empty (serving passes no degree bar)", "no salary in data",
                       "applicant_count/historical_apply_rate = 0 (as for live Adzuna jobs)",
                       "seeker skills extracted from past job titles + major only (CB has no skill list)",
                       "2012 US postings; app serves mostly 2020s Indian tech postings"],
        "cross_encoder": "skipped" if args.skip_ce else "fine-tuned cross_encoder_finetuned",
        "seconds": round(time.time() - t_start, 1),
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    log(json.dumps({k: manifest[k] for k in ("rows", "groups", "positives", "constant_features")}))
    return manifest


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Build the M2 ranker dataset from real CareerBuilder applications")
    ap.add_argument("--negatives", type=int, default=7)
    ap.add_argument("--same-state", type=int, default=4)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--max-users", type=int, default=0, help="subsample users (smoke tests)")
    ap.add_argument("--skip-ce", action="store_true")
    ap.add_argument("--threads", type=int, default=0, help="CPU threads (default: all but 2)")
    run(ap.parse_args(argv))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
