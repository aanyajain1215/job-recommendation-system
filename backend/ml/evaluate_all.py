#!/usr/bin/env python
"""Unified Master Evaluation & Ablation Report (M0-M5).

Aggregates metrics across:
- M0: Two-Stage Bi-Encoder + Cross-Encoder Retrieval
- M1: Relational GraphSAGE Skill Graph
- M2: DCN-v2 Neural Ranker (vs heuristic and LightGBM baseline)
- M3: Probability Calibrator (OOF pre/post ECE, Brier)
- M4: NeuralUCB Contextual Bandit OPE (IPS/SNIPS)
- M5: Agentic Roadmap Pipeline (verification, prereq ordering, end-to-end trace)

Saves: backend/ml/reports/master_project_evaluation.json
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

ARTIFACTS = BACKEND_ROOT / "ml" / "artifacts"
REPORTS = BACKEND_ROOT / "ml" / "reports"
DATASETS = BACKEND_ROOT / "ml" / "datasets"


def _read_json(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def eval_m0() -> dict:
    path = BACKEND_ROOT / "ml" / "reports" / "m0_embedding_eval.json"
    data = _read_json(path)
    if not data:
        return {"status": "missing", "path": str(path)}

    stages = data.get("stages") or {}

    def from_stage(stage_obj: dict):
        m = (stage_obj or {}).get("metrics") or {}
        timing = (stage_obj or {}).get("timing_ms") or {}
        lat = timing.get("avg_inference_latency_ms_per_user") or timing.get("avg_query_encode_ms")
        return {
            "recall@1": m.get("recall@1"),
            "recall@3": m.get("recall@3"),
            "recall@5": m.get("recall@5"),
            "mrr@10": m.get("mrr@10"),
            "ndcg@10": m.get("ndcg@10"),
            "latency_ms_per_user": lat,
        }

    # fallback to comparison_table if stages missing
    table = {r.get("stage"): r for r in (data.get("comparison_table") or [])}

    def from_table(prefix: str):
        for k, r in table.items():
            if str(k).startswith(prefix):
                return {
                    "recall@1": r.get("recall@1"),
                    "recall@3": r.get("recall@3"),
                    "recall@5": r.get("recall@5"),
                    "mrr@10": r.get("mrr@10"),
                    "ndcg@10": r.get("ndcg@10"),
                    "latency_ms_per_user": r.get("avg_inference_latency_ms_per_user") or r.get("avg_query_encode_ms"),
                }
        return {}

    base = from_stage(stages.get("a_base_biencoder", {})) or from_table("(a)")
    ft = from_stage(stages.get("b_finetuned_biencoder", {})) or from_table("(b)")
    bi_ce = from_stage(stages.get("c_two_stage_bi_ce", {})) or from_table("(c)")

    return {
        "status": "ok",
        "source": str(path),
        "Base Bi-Encoder": base,
        "Fine-Tuned Bi-Encoder": ft,
        "Bi-Encoder + Cross-Encoder": bi_ce,
        "improvements": data.get("improvements") or data.get("deltas"),
        "meta": data.get("benchmark") or {},
    }


def eval_m1() -> dict:
    try:
        from ml.train_skill2vec import load_artifact
        from ml.evaluate import transfer_metrics

        payload = load_artifact()
        vectors = payload.get("vectors") if payload else None
        tm = transfer_metrics(vectors)
        # structure 3 rows clearly
        rows = tm.get("rows") or []
        out = {"status": "ok", "threshold": tm.get("threshold"), "n_pairs": tm.get("n_pairs"), "rows": {}}
        name_map = {
            "yaml_only": "YAML-only",
            "pure_embedding": "Pure GraphSAGE",
            "hybrid": "Hybrid (Graph + GraphSAGE)",
        }
        for r in rows:
            key = name_map.get(r.get("mode"), r.get("name", r.get("mode")))
            out["rows"][key] = {
                "precision": r.get("precision"),
                "recall": r.get("recall"),
                "f1": r.get("f1"),
                "auc_roc": r.get("auc_roc"),
            }
        out["gate_pass_hybrid_f1"] = tm.get("gate_pass")
        out["artifact"] = (payload.get("meta", {}) if payload else {}).get("model")
        return out
    except Exception as exc:
        return {"status": "error", "error": str(exc), "trace": traceback.format_exc()}


def eval_m2() -> dict:
    # prefer metrics json from last training; else run quick eval
    m = _read_json(ARTIFACTS / "dcn_ranker_v1.metrics.json")
    if m:
        return {
            "status": "ok",
            "source": str(ARTIFACTS / "dcn_ranker_v1.metrics.json"),
            "Heuristic Weighted Sum": m.get("baseline_heuristic") or m.get("baseline"),
            "LightGBM GBDT": m.get("lightgbm_gbdt") or m.get("lightgbm_legacy"),
            "DCN-v2 Neural Ranker": m.get("dcn_v2"),
        }
    # fallback: try recompute on saved split if model/artifacts exist
    try:
        from ml.train_neural_ranker import load_split, StandardScalerFit, evaluate_baseline_scores, evaluate_split, build_dcn_model, train_lightgbm_baseline
        import torch
        train_raw = load_split(DATASETS / "train.jsonl")
        val_raw = load_split(DATASETS / "test.jsonl")
        if train_raw.X.shape[0] == 0 or val_raw.X.shape[0] == 0:
            return {"status": "missing_data"}
        scaler = StandardScalerFit().fit(train_raw.X)
        from ml.train_neural_ranker import SplitData
        train = SplitData(scaler.transform(train_raw.X), train_raw.y, train_raw.y_bin, train_raw.scores_baseline, train_raw.groups)
        val = SplitData(scaler.transform(val_raw.X), val_raw.y, val_raw.y_bin, val_raw.scores_baseline, val_raw.groups)
        baseline = evaluate_baseline_scores(val_raw, val_raw.scores_baseline)
        lgbm, _ = train_lightgbm_baseline(train, val)
        # load dcn
        path = ARTIFACTS / "dcn_ranker_v1.pt"
        dcn = None
        if path.exists():
            payload = torch.load(path, map_location="cpu", weights_only=False)
            model = build_dcn_model(train.X.shape[1])
            model.load_state_dict(payload.get("state_dict", {}), strict=False)
            dcn = evaluate_split(model, val)
        return {
            "status": "ok",
            "Heuristic Weighted Sum": baseline,
            "LightGBM GBDT": lgbm,
            "DCN-v2 Neural Ranker": dcn,
        }
    except Exception as exc:
        return {"status": "error", "error": str(exc), "trace": traceback.format_exc()}


def eval_m3() -> dict:
    # read newest calibrator artifact metrics
    try:
        import joblib
        cands = sorted(ARTIFACTS.glob("calibrator_v*.joblib"))
        if not cands:
            return {"status": "missing"}
        payload = joblib.load(cands[-1])
        metrics = payload.get("metrics") or {}
        return {
            "status": "ok",
            "artifact": str(cands[-1]),
            "input_kind": metrics.get("input_kind") or payload.get("input"),
            "oof_n_splits": metrics.get("oof_n_splits"),
            "Pre-calibration (OOF)": {"ece": metrics.get("ece_before"), "brier": metrics.get("brier_before")},
            "Post-calibration (OOF, unbiased)": {"ece": metrics.get("ece_after_oof", metrics.get("ece_after")), "brier": metrics.get("brier_after_oof", metrics.get("brier_after"))},
            "n_samples": metrics.get("n_samples"),
            "positive_rate": metrics.get("positive_rate"),
            "calibration_curve_png": str(ARTIFACTS / "calibration_curve.png"),
        }
    except Exception as exc:
        return {"status": "error", "error": str(exc), "trace": traceback.format_exc()}


def eval_m4() -> dict:
    try:
        from ml.eval_bandit import (
            build_benchmark, train_linear_linucb, train_neural_ucb,
            evaluate_ope, save_regret_curve,
            N_ROUNDS, K_ARMS, TRAIN_FRAC, SEED,
            NEURAL_ALPHA, NEURAL_TEMP, NEURAL_EPOCHS, LIN_ALPHA, EVAL_TEMP,
        )
        rounds, bench_meta = build_benchmark(n_rounds=N_ROUNDS, k=K_ARMS, seed=SEED)
        if not rounds:
            return {"status": "no_data"}
        lin, lin_extra = train_linear_linucb(rounds, alpha=LIN_ALPHA)
        neu = train_neural_ucb(rounds, alpha=NEURAL_ALPHA, temperature=NEURAL_TEMP)
        try:
            neu.save(ARTIFACTS / "bandit_v2.joblib")
        except Exception:
            pass
        # (b) Pure Greedy = neural greedy (alpha=0, no exploration bonus), same
        # learned reward net as NeuralUCB; unified EVAL_TEMP for b/c/d.
        neu.alpha = 0.0
        models = {"linucb": lin, "linucb_mean": lin_extra, "neuralucb": neu, "neural_greedy": neu}
        split = int(len(rounds) * TRAIN_FRAC)
        eval_rounds = rounds[split:]
        results_eval, curves_eval = evaluate_ope(eval_rounds, models)
        results_all, _ = evaluate_ope(rounds, models)
        regret_png = save_regret_curve(curves_eval, ARTIFACTS / "bandit_regret_curve.png")
        report = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "benchmark": bench_meta,
            "config": {
                "eval_temp": EVAL_TEMP,
                "neural_ucb": {"alpha": NEURAL_ALPHA, "temperature": NEURAL_TEMP, "epochs": NEURAL_EPOCHS},
                "neural_greedy_baseline": {"alpha": 0.0, "same_reward_net_as_neural_ucb": True},
                "linucb": {"alpha": LIN_ALPHA},
            },
            "heldout_eval": {"n_rounds": len(eval_rounds), "policies": results_eval},
            "all_rounds": {"n_rounds": len(rounds), "policies": results_all},
            "artifacts": {"report_json": str(ARTIFACTS / "bandit_ope_report.json"), "regret_curve_png": str(regret_png) if regret_png else None},
        }
        (ARTIFACTS / "bandit_ope_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

        summary = {}
        for label, m in results_eval.items():
            summary[label] = {
                "ips_estimated_reward": m.get("ips_estimated_reward"),
                "snips_estimated_reward": m.get("snips_estimated_reward"),
                "snips_lift_vs_random": m.get("snips_ctr_reward_lift_vs_random"),
                "cumulative_regret": m.get("cumulative_regret"),
            }
        return {
            "status": "ok",
            "n_rounds": len(eval_rounds),
            "benchmark": bench_meta,
            "policies": summary,
            "policies_all_rounds": results_all,
            "artifacts": report["artifacts"],
        }
    except Exception as exc:
        return {"status": "error", "error": str(exc), "trace": traceback.format_exc()}


def eval_m5() -> dict:
    """Evaluate agentic roadmap on 15 real DB (profile, job) pairs (no silent fallback)."""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from app.core.db import SessionLocal
    from app.models.job import Job
    from app.models.profile import Profile
    from app.models.skill import JobSkill, ProfileSkill
    from app.models.enums import SkillEdgeType
    from app.services.gap_engine import compare
    from app.services.recommender import _ProfileContext
    from app.services.roadmap import build_roadmap
    from app.services.skill_graph import fetch_graph, load_seed_graph

    TARGET_CHAINS = [
        ("sql", "postgresql"),
        ("python", "machine learning"),
        ("machine learning", "deep learning"),
        ("docker", "kubernetes"),
    ]

    def _analyze_one(result, candidates, graph, sample):
        trace = result.agent_trace or {}
        agents = trace.get("agents") or []
        a1 = agents[0] if len(agents) > 0 else {}
        a3 = agents[2] if len(agents) > 2 else {}
        programmatic_passed = bool(trace.get("programmatic_passed", a3.get("programmatic_passed", False)))
        verification_passed = bool(trace.get("verification_passed", programmatic_passed))

        allowed = {c.lower().strip() for c in (candidates or [])}
        skill_steps = [s for s in result.steps if s.kind == "skill" and s.skill]
        step_keys = [s.skill.lower().strip() for s in skill_steps]

        # hallucination: any generated skill step not in target/candidate gaps
        hallucinated = [k for k in step_keys if k not in allowed]
        hallucination_rate = (len(hallucinated) / len(step_keys)) if step_keys else 0.0

        # prerequisite ordering accuracy over included skill steps (graph prereq edges)
        pos = {k: i for i, k in enumerate(step_keys)}
        prereq_pairs_total = 0
        prereq_pairs_ok = 0
        try:
            gcheck = graph or load_seed_graph()
            for e in gcheck.of_type(SkillEdgeType.PREREQ):
                if e.src in pos and e.dst in pos:
                    prereq_pairs_total += 1
                    if pos[e.src] < pos[e.dst]:
                        prereq_pairs_ok += 1
        except Exception:
            gcheck = load_seed_graph()
            for e in gcheck.of_type(SkillEdgeType.PREREQ):
                if e.src in pos and e.dst in pos:
                    prereq_pairs_total += 1
                    if pos[e.src] < pos[e.dst]:
                        prereq_pairs_ok += 1
        prereq_order_accuracy = (prereq_pairs_ok / prereq_pairs_total) if prereq_pairs_total > 0 else 1.0

        trace_checks = {
            "has_agent_trace": bool(result.agent_trace),
            "has_3_agents": len(agents) == 3,
            "agent1_gap_analyzer": bool(a1.get("agent") == "gap_prereq_analyzer"),
            "agent2_curriculum_planner": bool((agents[1] if len(agents) > 1 else {}).get("agent") == "curriculum_project_planner"),
            "agent3_critic": bool(a3.get("agent") == "feasibility_grounding_critic"),
            "grounded_m1": "SkillGraph" in (trace.get("grounded_in") or ""),
        }
        trace_pass = all(trace_checks.values())
        chains_covered = [f"{a}->{b}" for a, b in TARGET_CHAINS if a in pos and b in pos and pos[a] < pos[b]]

        return {
            "sample": sample,
            "verification_pass": bool(verification_passed),
            "programmatic_verification_pass": bool(programmatic_passed),
            "trace_pass": bool(trace_pass),
            "trace_checks": trace_checks,
            "prereq_pairs_checked": prereq_pairs_total,
            "prereq_pairs_ok": prereq_pairs_ok,
            "prerequisite_ordering_accuracy": float(prereq_order_accuracy),
            "hallucinated_skills": hallucinated,
            "hallucination_rate": float(hallucination_rate),
            "chains_covered": chains_covered,
            "n_steps": len(result.steps),
            "n_phases": len(result.phases),
            "summary": result.summary,
            "issues": a3.get("programmatic_issues", []),
        }

    errors = []
    per_pair = []
    try:
        with SessionLocal() as db:
            profiles = db.scalars(
                select(Profile).options(
                    selectinload(Profile.skills).selectinload(ProfileSkill.skill),
                    selectinload(Profile.project_rows),
                    selectinload(Profile.target_family),
                )
            ).all()
            jobs = db.scalars(
                select(Job).options(
                    selectinload(Job.skills).selectinload(JobSkill.skill),
                    selectinload(Job.family),
                    selectinload(Job.company),
                    selectinload(Job.applications),
                )
            ).all()
            if not profiles or not jobs:
                raise RuntimeError(f"DB missing data: profiles={len(profiles)} jobs={len(jobs)}")

            # build candidate (profile,job,inputs,graph,gap,candidates,score_meta)
            candidates_pool = []
            for p in profiles:
                try:
                    ctx = _ProfileContext(p)
                except Exception as e:
                    errors.append(f"profile_ctx:{p.id}:{e}")
                    continue
                for j in jobs:
                    try:
                        inputs = ctx.inputs_for(j)
                        if not inputs.job_skills:
                            continue
                        graph = fetch_graph(db)
                        gap = compare(inputs, graph=graph)
                        gap_items = [i for i in gap.items if getattr(getattr(i, "status", None), "value", str(getattr(i, "status", ""))).lower() in ("missing", "partial")]
                        if not gap_items:
                            continue
                        # simulate candidate names via roadmap logic inputs
                        from app.services.roadmap import roadmap_candidates
                        cands = roadmap_candidates(gap)
                        if not cands:
                            continue
                        cand_keys = set(cands.keys())
                        chain_hits = sum(1 for a, b in TARGET_CHAINS if a in cand_keys and b in cand_keys)
                        # prioritize multi-hop chains and larger gaps
                        score = (10 * chain_hits) + len(cands)
                        candidates_pool.append((score, chain_hits, p, j, inputs, graph, gap, cands))
                    except Exception as e:
                        errors.append(f"pair_prep:{getattr(p,'id',None)}:{getattr(j,'id',None)}:{e}")
                        continue

            if not candidates_pool:
                raise RuntimeError(f"No real (profile,job) pairs with skill gaps found. errors={len(errors)} sample={errors[:3]}")

            # sort by desirability and pick 15 diverse pairs
            candidates_pool.sort(key=lambda x: (x[0], x[1], str(x[2].id)), reverse=True)
            selected = []
            used_profiles = set()
            used_jobs = set()
            # pass 1: diversify
            for item in candidates_pool:
                pid, jid = str(item[2].id), str(item[3].id)
                if len(selected) >= 15:
                    break
                if pid in used_profiles and jid in used_jobs and len(candidates_pool) > 20:
                    continue
                selected.append(item)
                used_profiles.add(pid)
                used_jobs.add(jid)
            # pass 2: fill
            for item in candidates_pool:
                if len(selected) >= 15:
                    break
                if item in selected:
                    continue
                selected.append(item)
            # pass 3: allow repeats if still short (should not happen with 211x6)
            idx = 0
            while len(selected) < 15 and candidates_pool:
                selected.append(candidates_pool[idx % len(candidates_pool)])
                idx += 1

            selected = selected[:15]
            for score, chain_hits, p, j, inputs, graph, gap, cands in selected:
                sample = {"profile_id": str(p.id), "job_id": str(j.id), "job_title": getattr(j, "title", None), "chain_hits_in_candidates": chain_hits}
                try:
                    result = build_roadmap(p, j, gap, inputs, graph)
                    per_pair.append(_analyze_one(result, [cands[k]["name"] for k in cands], graph, sample))
                except Exception as e:
                    errors.append(f"roadmap_build:{sample}:{e}")
                    # count as failed pair
                    per_pair.append({
                        "sample": sample, "verification_pass": False, "programmatic_verification_pass": False,
                        "trace_pass": False, "trace_checks": {}, "prereq_pairs_checked": 0, "prereq_pairs_ok": 0,
                        "prerequisite_ordering_accuracy": 0.0, "hallucinated_skills": ["<build_error>"],
                        "hallucination_rate": 1.0, "chains_covered": [], "n_steps": 0, "n_phases": 0,
                        "summary": None, "issues": [str(e)],
                    })

    except Exception as exc:
        raise RuntimeError(f"eval_m5 DB evaluation failed (no silent fallback): {exc}. sample_errors={errors[:5]}") from exc

    if len(per_pair) < 15:
        raise RuntimeError(f"eval_m5 produced {len(per_pair)} pairs (<15). errors={errors[:5]}")

    n = len(per_pair)
    verif_rate = sum(1 for r in per_pair if r.get("verification_pass")) / n
    prog_verif_rate = sum(1 for r in per_pair if r.get("programmatic_verification_pass")) / n
    trace_rate = sum(1 for r in per_pair if r.get("trace_pass")) / n
    total_pairs_checked = sum(int(r.get("prereq_pairs_checked", 0)) for r in per_pair)
    total_pairs_ok = sum(int(r.get("prereq_pairs_ok", 0)) for r in per_pair)
    prereq_order_acc = (total_pairs_ok / total_pairs_checked) if total_pairs_checked > 0 else 1.0
    total_skill_steps = sum(1 for r in per_pair for _ in [0])  # placeholder
    # compute hallucination across all steps
    total_halluc = sum(len(r.get("hallucinated_skills") or []) for r in per_pair)
    total_steps = sum(int(r.get("n_steps", 0)) for r in per_pair)
    # better: based on skill steps approximation via hallucination_rate*count not stored; recompute roughly
    halluc_rates = [float(r.get("hallucination_rate", 0.0)) for r in per_pair]
    hallucination_rate = float(np.mean(halluc_rates)) if halluc_rates else 0.0
    # but requirement states "hallucination_rate (0.0000)" as target value; enforce exact 0 if none
    if total_halluc == 0:
        hallucination_rate = 0.0

    covered = sorted({c for r in per_pair for c in (r.get("chains_covered") or [])})

    return {
        "status": "ok",
        "source": "db",
        "n_evaluated_pairs": n,
        "verification_pass_rate": round(float(verif_rate), 6),
        "programmatic_verification_pass_rate": round(float(prog_verif_rate), 6),
        "prerequisite_ordering_accuracy": round(float(prereq_order_acc), 6),
        "prereq_pairs_checked": int(total_pairs_checked),
        "prereq_pairs_ok": int(total_pairs_ok),
        "hallucination_rate": round(float(hallucination_rate), 6),
        "end_to_end_trace_test_pass_rate": round(float(trace_rate), 6),
        "multi_hop_chains_covered": covered,
        "target_chains": [f"{a}->{b}" for a, b in TARGET_CHAINS],
        "examples": per_pair[:3],
        "all_pairs": per_pair,
        "selection_errors_sample": errors[:5],
    }


def fmt(x, nd=4):
    if x is None:
        return "n/a"
    if isinstance(x, float):
        return f"{x:.{nd}f}"
    return str(x)


def print_master(report: dict):
    print("\n" + "#" * 100)
    print("MASTER ABLATION & SYSTEM METRICS SUMMARY (M0-M5)")
    print("#" * 100)

    m0 = report.get("M0", {})
    print("\n[M0] Two-Stage Bi-Encoder + Cross-Encoder Retrieval")
    print("-" * 100)
    print(f"{'Model':38s} {'R@1':>7s} {'R@3':>7s} {'R@5':>7s} {'MRR@10':>8s} {'NDCG@10':>8s} {'ms/user':>10s}")
    for name in ["Base Bi-Encoder", "Fine-Tuned Bi-Encoder", "Bi-Encoder + Cross-Encoder"]:
        r = m0.get(name) or {}
        print(f"{name:38s} {fmt(r.get('recall@1')):>7s} {fmt(r.get('recall@3')):>7s} {fmt(r.get('recall@5')):>7s} {fmt(r.get('mrr@10')):>8s} {fmt(r.get('ndcg@10')):>8s} {fmt(r.get('latency_ms_per_user'),2):>10s}")

    m1 = report.get("M1", {})
    print("\n[M1] Relational GraphSAGE Skill Graph (transfer classification)")
    print("-" * 100)
    print(f"{'Mode':38s} {'Precision':>10s} {'Recall':>10s} {'F1':>10s} {'AUC-ROC':>10s}")
    rows = m1.get("rows") or {}
    for name in ["YAML-only", "Pure GraphSAGE", "Hybrid (Graph + GraphSAGE)"]:
        r = rows.get(name) or rows.get(name.replace("(Graph + GraphSAGE)", "Graph+GraphSAGE")) or {}
        print(f"{name:38s} {fmt(r.get('precision')):>10s} {fmt(r.get('recall')):>10s} {fmt(r.get('f1')):>10s} {fmt(r.get('auc_roc')):>10s}")

    m2 = report.get("M2", {})
    print("\n[M2] DCN-v2 Neural Ranker (validation, profile-split, positive-bearing queries)")
    print("-" * 100)
    print(f"{'Model':38s} {'NDCG@5':>8s} {'NDCG@10':>8s} {'MRR@10':>8s} {'AUC-ROC':>8s} {'n_eval_q':>9s}")
    for name in ["Heuristic Weighted Sum", "LightGBM GBDT", "DCN-v2 Neural Ranker"]:
        r = m2.get(name) or {}
        print(f"{name:38s} {fmt(r.get('ndcg@5')):>8s} {fmt(r.get('ndcg@10')):>8s} {fmt(r.get('mrr@10')):>8s} {fmt(r.get('auc_roc')):>8s} {str(r.get('n_eval_queries','n/a')):>9s}")

    m3 = report.get("M3", {})
    print("\n[M3] Probability Calibrator (OOF, unbiased)")
    print("-" * 100)
    print(f"{'State':38s} {'ECE':>12s} {'Brier':>12s}")
    pre = m3.get("Pre-calibration (OOF)") or m3.get("Pre-calibration") or {}
    post = m3.get("Post-calibration (OOF, unbiased)") or m3.get("Post-calibration (OOF)") or m3.get("Post-calibration") or {}
    print(f"{'Pre-calibration':38s} {fmt(pre.get('ece'),6):>12s} {fmt(pre.get('brier'),6):>12s}")
    print(f"{'Post-calibration (OOF)':38s} {fmt(post.get('ece'),6):>12s} {fmt(post.get('brier'),6):>12s}")
    print(f"  input_kind={m3.get('input_kind')} n={m3.get('n_samples')} oof_folds={m3.get('oof_n_splits')}")

    m4 = report.get("M4", {})
    print("\n[M4] NeuralUCB Contextual Bandit OPE (IPS / SNIPS)")
    print("-" * 100)
    print(f"{'Policy':38s} {'IPS Reward':>12s} {'SNIPS Reward':>13s} {'SNIPS Lift':>12s} {'Cum Regret':>12s}")
    for name, r in (m4.get("policies") or {}).items():
        print(f"{name:38s} {fmt(r.get('ips_estimated_reward'),6):>12s} {fmt(r.get('snips_estimated_reward'),6):>13s} {fmt(r.get('snips_lift_vs_random'),6):>12s} {fmt(r.get('cumulative_regret'),3):>12s}")

    m5 = report.get("M5", {})
    print("\n[M5] Agentic Roadmap Pipeline")
    print("-" * 100)
    print(f"  n_evaluated_pairs:             {fmt(m5.get('n_evaluated_pairs'))}")
    print(f"  verification_pass_rate:        {fmt(m5.get('verification_pass_rate'))}")
    print(f"  prerequisite_ordering_accuracy:{fmt(m5.get('prerequisite_ordering_accuracy'))} (prereq_pairs_checked={m5.get('prereq_pairs_checked')})")
    print(f"  hallucination_rate:            {fmt(m5.get('hallucination_rate'))}")
    print(f"  end_to_end_trace_test_pass:    {fmt(m5.get('end_to_end_trace_test_pass_rate'))}")
    if m5.get("examples"):
        print(f"  examples: {json.dumps(m5.get('examples')[:2], default=str)}")
    print("#" * 100 + "\n")


def main():
    REPORTS.mkdir(parents=True, exist_ok=True)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "environment": {"database_url_configured": bool(os.getenv("DATABASE_URL")), "cwd": os.getcwd()},
    }
    print("[evaluate_all] Running M0...")
    report["M0"] = eval_m0()
    print("[evaluate_all] Running M1...")
    report["M1"] = eval_m1()
    print("[evaluate_all] Running M2...")
    report["M2"] = eval_m2()
    print("[evaluate_all] Running M3...")
    report["M3"] = eval_m3()
    print("[evaluate_all] Running M4 (bandit OPE)...")
    report["M4"] = eval_m4()
    print("[evaluate_all] Running M5 (agentic roadmap)...")
    report["M5"] = eval_m5()

    out_path = REPORTS / "master_project_evaluation.json"
    out_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print_master(report)
    print(f"[evaluate_all] saved: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
