#!/usr/bin/env python
"""Offline training + evaluation for the contextual bandit (RL) exploration policy.

This script can:
1) simulate a realistic bandit dataset (contextual, stochastic logging policy),
2) train a LinUCB policy offline,
3) evaluate with replay-style avg reward and IPS/SNIPS off-policy estimates,
4) save an artifact to ml/artifacts/simulation/bandit_v*.joblib (simulation study;
   the app does NOT load it - the live policy starts fresh and learns online).

It is dependency-light and can run without a database (simulation mode).
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from pathlib import Path

import joblib
import numpy as np

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.bandit import BANDIT_FEATURE_NAMES, D, LinUCBPolicy  # noqa: E402

# Simulation study only: kept OUT of ml/artifacts/ so the app never serves a
# policy trained on simulated clicks (the live bandit learns from real interactions).
ARTIFACTS = BACKEND_ROOT / "ml" / "artifacts" / "simulation"
DATASETS = BACKEND_ROOT / "ml" / "datasets"


def sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-20, min(20, x))))


def simulate_dataset(n_rounds: int = 3000, n_arms: int = 8, seed: int = 7) -> list[dict]:
    rng = random.Random(seed)
    np_rng = np.random.default_rng(seed)
    # latent true preference vector (unknown to learner) - emphasizes skill/semantic/location/salary fit
    theta_true = np.zeros(D, dtype=np.float64)
    weights = {
        "bias": 0.1,
        "match_score": 0.9,
        "skill": 1.1,
        "semantic": 0.8,
        "experience": 0.4,
        "education": 0.2,
        "project": 0.3,
        "location": 0.7,
        "salary": 0.6,
        "interest": 0.5,
        "missing_required_count": -0.9,
        "job_age_days": -0.1,
        "applicant_count": -0.05,
        "profile_completeness": 0.2,
        "is_remote": 0.15,
        "salary_disclosed": 0.1,
        "family_match": 0.5,
        "transfer_count": 0.25,
    }
    for i, name in enumerate(BANDIT_FEATURE_NAMES):
        theta_true[i] = weights.get(name, 0.0)

    rows = []
    for t in range(n_rounds):
        # user/context factors
        completeness = rng.uniform(0.3, 1.0)
        family_pref = rng.choice([0.0, 0.5, 1.0])
        remote_pref = rng.random() < 0.5
        X = []
        true_means = []
        for _ in range(n_arms):
            match = rng.uniform(0.25, 0.95)
            skill = np.clip(match + rng.uniform(-0.2, 0.2), 0, 1)
            semantic = np.clip(match + rng.uniform(-0.25, 0.25), 0, 1)
            experience = rng.uniform(0.2, 1.0)
            education = rng.uniform(0.4, 1.0)
            project = rng.uniform(0.1, 0.9)
            location = rng.uniform(0.3, 1.0)
            salary = rng.uniform(0.2, 1.0)
            interest = rng.uniform(0.2, 1.0)
            missing = rng.randint(0, 5)
            job_age = rng.uniform(0, 45)
            applicants = rng.uniform(0, 80)
            is_remote = 1.0 if (remote_pref and rng.random() < 0.7) or (not remote_pref and rng.random() < 0.3) else 0.0
            sal_disc = 1.0 if rng.random() < 0.7 else 0.0
            fam = family_pref if rng.random() < 0.6 else rng.choice([0.0, 0.5, 1.0])
            transfer = rng.randint(0, 3)
            x = np.array([
                1.0, match, skill, semantic, experience, education, project, location, salary, interest,
                missing / 10.0, job_age / 60.0, applicants / 100.0, completeness,
                is_remote, sal_disc, fam, transfer / 5.0,
            ], dtype=np.float64)
            X.append(x)
            mu = sigmoid(float(theta_true @ x) + rng.gauss(0, 0.05))
            true_means.append(mu)
        X = np.vstack(X)
        # logging policy: epsilon-greedy on noisy proxy of match score (biased, not optimal)
        proxy = X[:, 1] + 0.15 * X[:, 3] - 0.1 * X[:, 10] + np_rng.normal(0, 0.05, size=n_arms)
        eps = 0.2
        if rng.random() < eps:
            probs = np.ones(n_arms) / n_arms
        else:
            best = int(np.argmax(proxy))
            probs = np.ones(n_arms) * (eps / n_arms)
            probs[best] += 1.0 - eps
        a = int(np_rng.choice(n_arms, p=probs))
        p = float(max(1e-6, probs[a]))
        # reward: Bernoulli-like via threshold on latent mean with noise
        reward = 1.0 if rng.random() < true_means[a] else 0.0
        rows.append({
            "t": t,
            "X": X.tolist(),
            "action": a,
            "propensity": p,
            "reward": reward,
            "true_means": true_means,
        })
    return rows


def save_dataset(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def load_dataset(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def train_offline(rows: list[dict], alpha: float = 0.8, temperature: float = 0.5) -> LinUCBPolicy:
    policy = LinUCBPolicy(dim=D, alpha=alpha, temperature=temperature)
    for r in rows:
        X = np.asarray(r["X"], dtype=np.float64)
        a = int(r["action"])
        reward = float(r["reward"])
        policy.update(X[a], reward)
    policy.trained_at = "offline"
    return policy


def evaluate(rows: list[dict], policy: LinUCBPolicy) -> dict:
    # replay-like: when policy agrees with logged action, count reward; also direct model estimate
    # plus IPS/SNIPS using logged propensities and target-policy propensity
    n = len(rows)
    if n == 0:
        return {}
    agree_rewards = []
    ips_terms = []
    snips_num = []
    snips_den = []
    model_vals = []
    oracle_regrets = []
    for r in rows:
        X = np.asarray(r["X"], dtype=np.float64)
        a_logged = int(r["action"])
        p_logged = float(max(1e-6, r["propensity"]))
        reward = float(r["reward"])
        scores = policy.predict_scores(X)
        probs = policy.propensities(scores)
        a_pi = int(np.argmax(probs))  # greedy target for value estimate
        p_pi = float(max(1e-6, probs[a_pi]))
        model_vals.append(float(scores[a_pi]))
        if a_pi == a_logged:
            agree_rewards.append(reward)
            w = p_pi / p_logged
            ips_terms.append(w * reward)
            snips_num.append(w * reward)
            snips_den.append(w)
        true_means = r.get("true_means")
        if true_means:
            oracle = max(true_means)
            chosen = true_means[a_pi]
            oracle_regrets.append(oracle - chosen)
    avg_logged = sum(r["reward"] for r in rows) / n
    avg_agree = (sum(agree_rewards) / len(agree_rewards)) if agree_rewards else 0.0
    ips = (sum(ips_terms) / n) if ips_terms else 0.0
    snips = (sum(snips_num) / sum(snips_den)) if snips_den and sum(snips_den) > 0 else 0.0
    return {
        "n_rounds": n,
        "avg_logged_reward": round(avg_logged, 4),
        "avg_reward_on_agreement": round(avg_agree, 4),
        "agreement_rate": round(len(agree_rewards) / n, 4),
        "ips_estimate": round(ips, 4),
        "snips_estimate": round(snips, 4),
        "mean_target_score": round(float(np.mean(model_vals)), 4) if model_vals else 0.0,
        "mean_oracle_regret": round(float(np.mean(oracle_regrets)), 4) if oracle_regrets else None,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Train/eval contextual bandit (RL) policy")
    parser.add_argument("--simulate", type=int, default=3000, help="number of simulated rounds (0 to skip)")
    parser.add_argument("--dataset", type=str, default=str(DATASETS / "bandit_sim.jsonl"))
    parser.add_argument("--alpha", type=float, default=0.8)
    parser.add_argument("--temperature", type=float, default=0.5)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--version", type=str, default="v1")
    parser.add_argument("--no-save", action="store_true")
    args = parser.parse_args(argv)

    dataset_path = Path(args.dataset)
    if args.simulate > 0 or not dataset_path.exists():
        rows = simulate_dataset(n_rounds=max(500, args.simulate), seed=args.seed)
        save_dataset(rows, dataset_path)
        print(f"[bandit] simulated dataset: {dataset_path} ({len(rows)} rounds)")
    else:
        rows = load_dataset(dataset_path)
        print(f"[bandit] loaded dataset: {dataset_path} ({len(rows)} rounds)")

    split = int(len(rows) * 0.8)
    train_rows = rows[:split]
    test_rows = rows[split:]
    policy = train_offline(train_rows, alpha=args.alpha, temperature=args.temperature)
    policy.model_version = args.version

    train_metrics = evaluate(train_rows, policy)
    test_metrics = evaluate(test_rows, policy)
    report = {
        "model": "contextual_bandit_linucb",
        "version": args.version,
        "feature_dim": D,
        "features": BANDIT_FEATURE_NAMES,
        "train": train_metrics,
        "test": test_metrics,
    }
    print(json.dumps(report, indent=2))

    if not args.no_save:
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        out = ARTIFACTS / f"bandit_{args.version}.joblib"
        policy.save(out)
        meta = out.with_suffix(".json")
        meta.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"[bandit] saved artifact: {out}")
        print(f"[bandit] saved report: {meta}")
        # best-effort registry entry (optional; requires DB)
        try:
            import ml.ml_registry as registry

            registry.register(
                "bandit",
                args.version,
                str(out),
                metrics={"test": test_metrics, "train": train_metrics, "feature_dim": D},
                promote=True,
            )
            print(f"[bandit] registered in model_registry as bandit {args.version} (active)")
        except Exception as exc:
            print(f"[bandit] registry skipped: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
