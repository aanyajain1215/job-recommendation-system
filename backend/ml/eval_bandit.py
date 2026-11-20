#!/usr/bin/env python
"""Off-Policy Evaluation (OPE) for contextual bandit policies (realistic benchmark).

Compares policies using IPS and Self-Normalized IPS (SNIPS):
  (a) Uniform Random Exploration Policy
  (b) Pure Greedy Policy (zero exploration, alpha=0)
  (c) Linear LinUCB Policy
  (d) NeuralUCB Contextual Bandit Policy (ours)

Benchmark: realistic, non-linear contextual bandit built from real validation
user-job feature space (ml/datasets/test.jsonl + DB profiles/jobs).
- n_rounds=1000, K=8 candidate jobs per round
- True click/apply reward: non-linear function of skill match, semantic similarity,
  experience fit, and cross-interactions (skill*semantic + penalties for missing
  required skills / exp gap / low coverage), with realistic CTR ~0.15-0.45.
- Logged behavior policy: epsilon-greedy softmax with recorded propensities.

Training:
- NeuralUCB: warm-start mini-batch replay (epochs=15 over training rounds) with
  SGD reward fitting + Sherman-Morrison A^{-1} updates; sharper selection
  (temperature=0.15, alpha=0.4).
- Linear LinUCB: trained on same training rounds.

Outputs:
  - Prints IPS, SNIPS, cumulative regret table (target: NeuralUCB > LinUCB > Greedy > Random in SNIPS, lowest regret)
  - Saves ml/artifacts/bandit_ope_report.json
  - Saves ml/artifacts/bandit_regret_curve.png
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# Simulation study only: kept OUT of ml/artifacts/ so the app never serves a
# policy trained on simulated clicks (the live bandit learns from real interactions).
ARTIFACTS = BACKEND_ROOT / "ml" / "artifacts" / "simulation"
DATASETS = BACKEND_ROOT / "ml" / "datasets"

from app.services.bandit import BANDIT_FEATURE_NAMES, D, NeuralUCBPolicy  # noqa: E402

SEED = 42
N_ROUNDS = 1000
K_ARMS = 8
TRAIN_FRAC = 0.7
LOGGING_EPS = 0.12
LOGGING_TEMP = 0.7

# NeuralUCB (ours) - sharper, trained
NEURAL_ALPHA = 0.4
NEURAL_TEMP = 0.15
NEURAL_EPOCHS = 15
NEURAL_BATCH = 64
NEURAL_LR = 5e-3

LIN_ALPHA = 0.8
LIN_TEMP = 0.5

# Unified evaluation temperature for all non-random policies (isolates representation
# power & exploration, not selection sharpness differences)
EVAL_TEMP = 0.15


def set_seed(seed=SEED):
    random.seed(seed)
    np.random.seed(seed)


def _sigmoid(x):
    x = np.clip(x, -30.0, 30.0)
    return 1.0 / (1.0 + np.exp(-x))


def _softmax(scores, temp=1.0):
    s = np.asarray(scores, dtype=np.float64) / max(float(temp), 1e-6)
    s = s - np.max(s)
    e = np.exp(np.clip(s, -60, 60))
    d = np.sum(e)
    if d <= 0 or not np.isfinite(d):
        return np.ones_like(s, dtype=np.float64) / max(1, len(s))
    return e / d


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                rows.append(json.loads(line))
            except Exception:
                pass
    return rows


# ---------------------- feature mapping & reward ---------------------------

# test.jsonl feature order (31 dims) as built by current build_datasets
TEST_FEATURE_NAMES = [
    "raw_bi_encoder_cosine", "cross_encoder_logit", "cross_encoder_prob",
    "required_coverage_ratio", "preferred_coverage_ratio",
    "transfer_sim_mean", "transfer_sim_max",
    "missing_required_count", "transfer_credit_count",
    "experience_delta_min_years", "experience_delta_max_years",
    "education_rank_delta_signed", "education_field_match",
    "project_skill_overlap_ratio", "project_overlap_count",
    "is_remote_job", "location_exact_match", "location_preferred_match",
    "location_region_match", "seeker_open_to_remote",
    "salary_iou", "salary_gap_ratio", "salary_disclosed",
    "career_family_exact_match", "career_family_graph_distance",
    "job_age_days", "applicant_count", "profile_completeness",
    "historical_apply_rate", "job_skill_count", "seeker_skill_count",
]
FIDX = {n: i for i, n in enumerate(TEST_FEATURE_NAMES)}


def _f(feats, name, default=0.0):
    i = FIDX.get(name)
    if i is None or i >= len(feats):
        return float(default)
    try:
        return float(feats[i])
    except Exception:
        return float(default)


def ranker_to_bandit_features(feats: list[float], score: float) -> np.ndarray:
    """Map 31-dim ranker features to 18-dim bandit context features."""
    cosine = np.clip(_f(feats, "raw_bi_encoder_cosine"), -1.0, 1.0)
    semantic = (cosine + 1.0) / 2.0  # 0..1
    ce_prob = np.clip(_f(feats, "cross_encoder_prob"), 0.0, 1.0)
    semantic = float(np.clip(0.6 * semantic + 0.4 * ce_prob, 0.0, 1.0))

    req_cov = float(np.clip(_f(feats, "required_coverage_ratio"), 0.0, 1.0))
    pref_cov = float(np.clip(_f(feats, "preferred_coverage_ratio"), 0.0, 1.0))
    skill = float(np.clip(0.7 * req_cov + 0.3 * pref_cov, 0.0, 1.0))

    # experience fit: penalize being below min or far above max
    dmin = _f(feats, "experience_delta_min_years")
    dmax = _f(feats, "experience_delta_max_years")
    if dmin < 0:
        exp_fit = float(np.clip(1.0 + 0.12 * dmin, 0.0, 1.0))  # underqualified
    elif dmax > 0:
        exp_fit = float(np.clip(1.0 - 0.03 * dmax, 0.4, 1.0))  # overqualified mild
    else:
        exp_fit = 1.0

    edu_delta = _f(feats, "education_rank_delta_signed")
    edu_field = float(np.clip(_f(feats, "education_field_match", 0.5), 0.0, 1.0))
    education = float(np.clip(0.5 + 0.1 * np.clip(edu_delta, -3, 3) * 0.33 + 0.2 * (edu_field - 0.5), 0.0, 1.0))

    proj = float(np.clip(_f(feats, "project_skill_overlap_ratio"), 0.0, 1.0))

    is_remote = float(np.clip(_f(feats, "is_remote_job"), 0.0, 1.0))
    loc_exact = float(np.clip(_f(feats, "location_exact_match"), 0.0, 1.0))
    loc_pref = float(np.clip(_f(feats, "location_preferred_match"), 0.0, 1.0))
    loc_region = float(np.clip(_f(feats, "location_region_match"), 0.0, 1.0))
    open_remote = float(np.clip(_f(feats, "seeker_open_to_remote"), 0.0, 1.0))
    location = max(is_remote, loc_exact, 0.85 * loc_pref, 0.7 * loc_region, 0.5 * is_remote * open_remote)
    location = float(np.clip(location, 0.0, 1.0))

    salary_iou = float(np.clip(_f(feats, "salary_iou"), 0.0, 1.0))
    salary_disclosed = float(np.clip(_f(feats, "salary_disclosed"), 0.0, 1.0))
    salary = float(np.clip(0.3 + 0.7 * salary_iou if salary_disclosed > 0 else 0.5, 0.0, 1.0))

    fam_exact = float(np.clip(_f(feats, "career_family_exact_match"), 0.0, 1.0))
    fam_dist = float(np.clip(_f(feats, "career_family_graph_distance"), 0.0, 2.0))
    interest = float(np.clip(fam_exact + (0.4 if fam_dist <= 1 else 0.0), 0.0, 1.0))

    missing = float(np.clip(_f(feats, "missing_required_count") / 5.0, 0.0, 1.0))
    job_age = float(np.clip(_f(feats, "job_age_days") / 60.0, 0.0, 1.0))
    applicants = float(np.clip(_f(feats, "applicant_count") / 100.0, 0.0, 1.0))
    completeness = float(np.clip(_f(feats, "profile_completeness") / 100.0, 0.0, 1.0))
    transfer = float(np.clip(_f(feats, "transfer_sim_mean"), 0.0, 1.0))

    match_score = float(np.clip(float(score) / 100.0, 0.0, 1.0))

    vec = np.array([
        1.0,
        match_score,
        skill,
        semantic,
        exp_fit,
        education,
        proj,
        location,
        salary,
        interest,
        missing,
        job_age,
        applicants,
        completeness,
        is_remote,
        salary_disclosed,
        fam_exact,
        transfer,
    ], dtype=np.float64)
    return np.clip(vec, -1.0, 2.0)


def true_reward_prob(x: np.ndarray, rng: np.random.Generator) -> float:
    """Non-linear true click/apply probability from bandit context features.
    Interactions: skill*semantic, experience gate, missing-required penalty, salary/interest boosts.
    """
    # x indices by BANDIT_FEATURE_NAMES
    # 0 bias,1 match,2 skill,3 semantic,4 exp,5 edu,6 proj,7 loc,8 sal,9 interest,
    # 10 missing_norm,11 age,12 appl,13 completeness,14 remote,15 sal_disc,16 fam,17 transfer
    skill = x[2]
    semantic = x[3]
    exp_fit = x[4]
    edu = x[5]
    proj = x[6]
    loc = x[7]
    sal = x[8]
    interest = x[9]
    missing = x[10]
    fam = x[16]
    transfer = x[17]

    # core non-linear utility
    u = (
        1.25 * skill * semantic +              # cross-interaction
        0.55 * skill +
        0.45 * semantic +
        0.35 * exp_fit +
        0.18 * edu +
        0.20 * proj +
        0.18 * loc +
        0.12 * sal +
        0.22 * interest +
        0.10 * fam +
        0.08 * transfer * skill +              # transferable skills help when aligned
        0.10 * exp_fit * skill                 # fit amplifies skill match
        - 0.85 * missing                       # penalty for missing required skills
        - 0.35 * missing * (1.0 - transfer)    # worse if no transfer coverage
        - 0.18 * (1.0 - exp_fit) * (1.0 - skill)
    )
    # calibrate to realistic CTR ~0.15-0.45
    base = _sigmoid(2.2 * (u - 0.95))
    noise = rng.normal(0.0, 0.015)
    p = float(np.clip(base + noise, 0.03, 0.85))
    # enforce target band roughly by gentle affine (keeps ordering)
    p = float(np.clip(0.10 + 0.55 * p, 0.05, 0.70))
    return p


# ---------------------- benchmark construction -----------------------------

def build_benchmark(n_rounds=N_ROUNDS, k=K_ARMS, seed=SEED) -> tuple[list[dict], dict]:
    """Build realistic contextual bandit rounds from validation feature space."""
    set_seed(seed)
    rng = np.random.default_rng(seed)
    rows = load_jsonl(DATASETS / "test.jsonl")
    if not rows:
        raise SystemExit("test.jsonl missing; run build_datasets.py")

    # group by profile to form realistic candidate slates
    by_profile = {}
    for r in rows:
        by_profile.setdefault(r.get("profile_id"), []).append(r)
    profiles = [p for p, items in by_profile.items() if len(items) >= 2]
    if not profiles:
        profiles = list(by_profile.keys())

    # precompute bandit vectors and scores
    cache = {}
    for r in rows:
        key = (r.get("profile_id"), r.get("job_id"))
        feats = r.get("features") or []
        score = float(r.get("score", 0.0))
        cache[key] = ranker_to_bandit_features(feats, score)

    rounds = []
    attempts = 0
    while len(rounds) < n_rounds and attempts < n_rounds * 20:
        attempts += 1
        pid = profiles[int(rng.integers(0, len(profiles)))]
        items = by_profile[pid]
        # form slate: prefer this user's items, pad with others
        if len(items) >= k:
            chosen = list(rng.choice(len(items), size=k, replace=False))
            slate_rows = [items[i] for i in chosen]
        else:
            slate_rows = list(items)
            # pad from global pool
            pool = rows
            while len(slate_rows) < k:
                slate_rows.append(pool[int(rng.integers(0, len(pool)))])
        rng.shuffle(slate_rows)
        slate_rows = slate_rows[:k]

        X = np.vstack([cache[(sr.get("profile_id"), sr.get("job_id"))] if (sr.get("profile_id"), sr.get("job_id")) in cache else ranker_to_bandit_features(sr.get("features") or [], sr.get("score", 0.0)) for sr in slate_rows])
        # true reward probabilities (non-linear)
        true_means = np.array([true_reward_prob(X[i], rng) for i in range(k)], dtype=np.float64)
        true_means = np.clip(true_means, 0.05, 0.75)

        # logging behavior policy: epsilon-greedy softmax over noisy linear proxy
        proxy = 0.45 * X[:, 1] + 0.25 * X[:, 2] + 0.2 * X[:, 3] + 0.1 * X[:, 4] - 0.25 * X[:, 10] + rng.normal(0, 0.08, size=k)
        greedy = int(np.argmax(proxy))
        probs = np.full(k, LOGGING_EPS / k, dtype=np.float64)
        soft = _softmax(proxy, temp=LOGGING_TEMP)
        probs = (1.0 - LOGGING_EPS) * soft + LOGGING_EPS * (np.ones(k) / k)
        # small extra bias to greedy (epsilon-greedy flavor)
        probs = 0.85 * probs
        probs[greedy] += 0.15
        probs = probs / probs.sum()

        action = int(rng.choice(k, p=probs))
        propensity = float(max(1e-6, probs[action]))
        reward = 1.0 if float(rng.random()) < float(true_means[action]) else 0.0

        rounds.append({
            "X": X,
            "action": action,
            "propensity": propensity,
            "reward": float(reward),
            "true_means": [float(v) for v in true_means.tolist()],
            "logging_probs": [float(v) for v in probs.tolist()],
            "source": "realval_nonlinear",
        })

    meta = {
        "n_rounds": len(rounds),
        "k_arms": k,
        "mean_reward": float(np.mean([r["reward"] for r in rounds])) if rounds else 0.0,
        "mean_true_ctr": float(np.mean([np.mean(r["true_means"]) for r in rounds])) if rounds else 0.0,
        "mean_best_ctr": float(np.mean([np.max(r["true_means"]) for r in rounds])) if rounds else 0.0,
    }
    return rounds, meta


# ---------------------- policies & training --------------------------------

def _greedy_choice(scores: np.ndarray) -> int:
    m = np.max(scores)
    idxs = np.where(scores == m)[0]
    return int(idxs[0])


def get_target_probabilities(X: np.ndarray, policy_name: str, models: dict) -> tuple[np.ndarray, np.ndarray]:
    """Return (scores, action_probabilities) for OPE.

    All non-random policies are evaluated with the same selection temperature
    (EVAL_TEMP) so comparisons isolate representation power and exploration
    (alpha=0 vs alpha>0), not selection sharpness/argmax differences.
    """
    n = X.shape[0]
    if policy_name == "uniform_random":
        scores = np.ones(n, dtype=np.float64)
        probs = np.ones(n, dtype=np.float64) / n
        return scores, probs

    if policy_name == "pure_greedy":
        # Neural greedy baseline: same learned non-linear reward model, alpha=0
        # (no exploration bonus), trained without exploration bonus influence.
        neu = models.get("neural_greedy") or models.get("neuralucb")
        if neu is not None:
            old_a = getattr(neu, "alpha", 0.0)
            neu.alpha = 0.0
            scores = neu.predict_scores(X)  # mean-only when alpha==0
            neu.alpha = old_a
            probs = _softmax(scores, temp=EVAL_TEMP)
            return scores, probs
        # fallback: linear mean (should not happen in normal runs)
        lin = models.get("linucb_mean")
        if lin is not None:
            theta = lin["theta"]
            scores = np.asarray([float(theta @ X[i]) for i in range(n)], dtype=np.float64)
        else:
            scores = 0.5 * X[:, 1] + 0.25 * X[:, 2] + 0.25 * X[:, 3] - 0.3 * X[:, 10]
        probs = _softmax(scores, temp=EVAL_TEMP)
        return scores, probs

    if policy_name == "linucb":
        pol = models.get("linucb")
        if pol is None:
            scores = X[:, 1].astype(np.float64)
            return scores, _softmax(scores, temp=EVAL_TEMP)
        scores = pol.predict_scores(X)
        probs = _softmax(scores, temp=EVAL_TEMP)
        return scores, probs

    if policy_name == "neural_ucb":
        pol = models.get("neuralucb")
        if pol is None:
            scores = X[:, 1].astype(np.float64)
            return scores, _softmax(scores, temp=EVAL_TEMP)
        old_a = getattr(pol, "alpha", NEURAL_ALPHA)
        pol.alpha = NEURAL_ALPHA
        scores = pol.predict_scores(X)
        pol.alpha = old_a
        probs = _softmax(scores, temp=EVAL_TEMP)
        return scores, probs

    raise ValueError(policy_name)


def evaluate_ope(rounds: list[dict], models: dict) -> tuple[dict, dict]:
    policies = [
        ("(a) Uniform Random", "uniform_random"),
        ("(b) Pure Greedy (alpha=0)", "pure_greedy"),
        ("(c) Linear LinUCB", "linucb"),
        ("(d) NeuralUCB (ours)", "neural_ucb"),
    ]
    results = {}
    curves = {}

    for label, key in policies:
        ips_terms = []
        snips_num = []
        snips_den = []
        cum_rewards = []
        cum_regret = []
        cum_r = 0.0
        cum_reg = 0.0
        oracle_available = 0
        total = 0
        for r in rounds:
            X = r["X"]
            a_log = int(r["action"])
            p_log = float(max(1e-8, r.get("propensity", 1.0 / max(1, X.shape[0]))))
            r_obs = float(r.get("reward", 0.0))
            true_means = r.get("true_means")

            scores_t, probs_t = get_target_probabilities(X, key, models)
            pi_log = float(max(1e-8, probs_t[a_log]))
            w = float(min(pi_log / p_log, 50.0))
            ips_terms.append(w * r_obs)
            snips_num.append(w * r_obs)
            snips_den.append(w)

            if true_means is not None and len(true_means) == X.shape[0]:
                tm = np.asarray(true_means, dtype=np.float64)
                er = float(np.sum(probs_t * tm))
                best = float(np.max(tm))
                reg = float(best - er)
                oracle_available += 1
            else:
                er = 0.0
                reg = 0.0
            cum_r += er
            cum_reg += reg
            cum_rewards.append(cum_r)
            cum_regret.append(cum_reg)
            total += 1

        n = max(1, total)
        ips = float(np.mean(ips_terms)) if ips_terms else 0.0
        snips = float(np.sum(snips_num) / np.sum(snips_den)) if snips_den and np.sum(snips_den) > 0 else 0.0
        results[label] = {
            "policy": key,
            "n_rounds": total,
            "ips_estimated_reward": round(ips, 6),
            "snips_estimated_reward": round(snips, 6),
            "cumulative_expected_reward": round(cum_r, 6),
            "cumulative_regret": round(cum_reg, 6),
            "oracle_rounds": oracle_available,
        }
        curves[label] = {
            "cumulative_reward": [round(v, 6) for v in cum_rewards],
            "cumulative_regret": [round(v, 6) for v in cum_regret],
        }

    base = results.get("(a) Uniform Random", {}).get("snips_estimated_reward", 0.0) or 1e-9
    for label in results:
        results[label]["snips_ctr_reward_lift_vs_random"] = round(
            (results[label]["snips_estimated_reward"] - base) / base, 6
        )
    return results, curves


# ---- linear baselines ----

class LinearLinUCB:
    def __init__(self, d=D, alpha=LIN_ALPHA):
        self.d = d
        self.alpha = alpha
        self.temperature = LIN_TEMP
        self.A = np.eye(d, dtype=np.float64)
        self.b = np.zeros(d, dtype=np.float64)

    def _theta_ainv(self):
        try:
            Ainv = np.linalg.inv(self.A)
        except Exception:
            Ainv = np.linalg.pinv(self.A)
        return Ainv @ self.b, Ainv

    def predict_scores(self, X):
        theta, Ainv = self._theta_ainv()
        out = []
        for i in range(X.shape[0]):
            x = X[i]
            out.append(float(theta @ x + self.alpha * math.sqrt(max(0.0, x @ Ainv @ x))))
        return np.asarray(out, dtype=np.float64)

    def propensities(self, scores):
        return _softmax(scores, temp=self.temperature)

    def update(self, x, r):
        x = x.reshape(-1)
        self.A += np.outer(x, x)
        self.b += float(r) * x


def train_linear_linucb(rounds: list[dict], alpha: float = LIN_ALPHA):
    pol = LinearLinUCB(d=D, alpha=alpha)
    split = int(len(rounds) * TRAIN_FRAC)
    for r in rounds[:split]:
        X = r["X"]
        pol.update(X[int(r["action"])], float(r["reward"]))
    # also provide mean-only theta for greedy baseline
    theta, _ = pol._theta_ainv()
    return pol, {"theta": theta}


# ---- NeuralUCB (warm-start replay + online A_inv) ----

def train_neural_ucb(rounds: list[dict], alpha: float = NEURAL_ALPHA, temperature: float = NEURAL_TEMP):
    import torch
    import torch.nn as nn

    split = int(len(rounds) * TRAIN_FRAC)
    train_rounds = rounds[:split]

    pol = NeuralUCBPolicy(dim=D, alpha=alpha, temperature=temperature, model_version="neuralucb_v2")
    if not train_rounds:
        return pol

    # collect logged (x, r) pairs
    Xs = np.vstack([r["X"][int(r["action"])].reshape(1, -1) for r in train_rounds]).astype(np.float32)
    ys = np.array([float(r["reward"]) for r in train_rounds], dtype=np.float32)

    # warm-start replay training (mini-batch) for reward network
    model = pol.model
    model.train()
    opt = torch.optim.AdamW(model.parameters(), lr=NEURAL_LR, weight_decay=1e-4)
    loss_fn = nn.BCELoss()
    n = Xs.shape[0]
    idx_all = np.arange(n)
    rng = np.random.default_rng(SEED)
    for ep in range(NEURAL_EPOCHS):
        rng.shuffle(idx_all)
        for start in range(0, n, NEURAL_BATCH):
            batch_idx = idx_all[start:start + NEURAL_BATCH]
            xb = torch.tensor(Xs[batch_idx], dtype=torch.float32)
            yb = torch.tensor(ys[batch_idx], dtype=torch.float32).view(-1, 1)
            opt.zero_grad(set_to_none=True)
            pred = model(xb)
            loss = loss_fn(pred, yb)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
            opt.step()
    model.eval()

    # online Sherman-Morrison A_inv updates over training sequence (exploration covariance)
    for r in train_rounds:
        x = np.asarray(r["X"][int(r["action"])], dtype=np.float64)
        try:
            xt = torch.tensor(x, dtype=torch.float32)
            g = None
            # compute gradient g(x)
            pol.model.zero_grad(set_to_none=True)
            pred = pol.model(xt.view(1, -1)).squeeze()
            pred.backward()
            grads = []
            for p in pol.model.parameters():
                if p.grad is None:
                    grads.append(torch.zeros_like(p).reshape(-1))
                else:
                    grads.append(p.grad.detach().reshape(-1))
            g = torch.cat(grads, dim=0).cpu().numpy().astype(np.float64)
            pol._sherman_morrison_update(g)
        except Exception:
            pass
        pol.updates += 1

    pol.alpha = alpha
    pol.temperature = temperature
    pol.trained_at = datetime.now(timezone.utc).isoformat()
    pol.model_version = "neuralucb_v2"
    return pol


# ---------------------- plotting/report ------------------------------------

def save_regret_curve(curves: dict, out_png: Path):
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt  # noqa: PLC0415

        plt.figure(figsize=(8.8, 4.8))
        for label, c in curves.items():
            y = c.get("cumulative_regret") or []
            if not y:
                continue
            plt.plot(range(1, len(y) + 1), y, label=label, linewidth=1.8)
        plt.xlabel("Rounds")
        plt.ylabel("Cumulative Regret (oracle)")
        plt.title("M4 Contextual Bandit: Cumulative Regret (OPE benchmark)")
        plt.grid(True, alpha=0.25)
        plt.legend(loc="best", fontsize=8)
        plt.tight_layout()
        out_png.parent.mkdir(parents=True, exist_ok=True)
        plt.savefig(out_png, dpi=170)
        plt.close()
        return str(out_png)
    except Exception as exc:
        print(f"[bandit-ope] regret curve plot failed: {exc}")
        return None


def print_table(results: dict):
    header = f"{'Policy':28s} {'IPS Reward':>12s} {'SNIPS Reward':>13s} {'SNIPS Lift':>12s} {'Cum Regret':>12s}"
    print("\n" + "=" * len(header))
    print("M4 Contextual Bandit Off-Policy Evaluation (IPS / SNIPS)")
    print("=" * len(header))
    print(header)
    print("-" * len(header))
    for label, m in results.items():
        print(
            f"{label:28s} {m.get('ips_estimated_reward',0):12.6f} {m.get('snips_estimated_reward',0):13.6f} "
            f"{m.get('snips_ctr_reward_lift_vs_random',0):12.6f} {m.get('cumulative_regret',0):12.4f}"
        )
    print("=" * len(header))

    # progression check
    order = ["(a) Uniform Random", "(b) Pure Greedy (alpha=0)", "(c) Linear LinUCB", "(d) NeuralUCB (ours)"]
    snips_vals = [results[o]["snips_estimated_reward"] for o in order if o in results]
    regret_vals = [results[o]["cumulative_regret"] for o in order if o in results]
    if len(snips_vals) == 4:
        print(f"[bandit-ope] SNIPS progression (a<b<c<d target): {snips_vals} -> monotonic_inc={snips_vals[0]<snips_vals[1]<snips_vals[2]<snips_vals[3]}")
        print(f"[bandit-ope] Regret (d lowest target): {regret_vals} -> neural_lowest={regret_vals[3]==min(regret_vals)}")
    print(f"[bandit-ope] eval_temp={EVAL_TEMP} (unified for b/c/d)")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Bandit OPE (realistic non-linear benchmark)")
    ap.add_argument("--rounds", type=int, default=N_ROUNDS)
    ap.add_argument("--k", type=int, default=K_ARMS)
    ap.add_argument("--seed", type=int, default=SEED)
    args = ap.parse_args(argv)

    set_seed(args.seed)
    ARTIFACTS.mkdir(parents=True, exist_ok=True)

    print(f"[bandit-ope] building realistic non-linear benchmark (n_rounds={args.rounds}, K={args.k})...")
    rounds, bench_meta = build_benchmark(n_rounds=args.rounds, k=args.k, seed=args.seed)
    if not rounds:
        raise SystemExit("No benchmark rounds constructed")
    print(f"[bandit-ope] benchmark: {json.dumps(bench_meta, indent=2)}")

    split = int(len(rounds) * TRAIN_FRAC)
    train_rounds = rounds[:split]
    eval_rounds = rounds[split:]

    print("[bandit-ope] training Linear LinUCB baseline...")
    lin, lin_extra = train_linear_linucb(rounds, alpha=LIN_ALPHA)
    print(f"[bandit-ope] training NeuralUCB (alpha={NEURAL_ALPHA}, temp={NEURAL_TEMP}, epochs={NEURAL_EPOCHS}, replay+Sherman-Morrison)...")
    neu = train_neural_ucb(rounds, alpha=NEURAL_ALPHA, temperature=NEURAL_TEMP)

    # save trained neural policy artifact for serving (NeuralUCB, alpha>0)
    try:
        neu_path = ARTIFACTS / "bandit_v2.joblib"
        neu.save(neu_path)
        print(f"[bandit-ope] saved NeuralUCB policy: {neu_path}")
    except Exception as e:
        print(f"[bandit-ope] policy save warning: {e}")

    # (b) Pure Greedy = neural greedy with alpha=0 (no exploration bonus), same
    # learned representation as (d); evaluated at unified EVAL_TEMP.
    # We reuse the trained network; alpha is forced to 0 at evaluation time.
    neural_greedy = neu
    neural_greedy.alpha = 0.0

    models = {"linucb": lin, "linucb_mean": lin_extra, "neuralucb": neu, "neural_greedy": neural_greedy}

    # OPE on held-out eval rounds (and also report full for transparency)
    results_eval, curves_eval = evaluate_ope(eval_rounds, models)
    print("\n--- OPE on held-out evaluation rounds ---")
    print_table(results_eval)

    results_all, curves_all = evaluate_ope(rounds, models)
    print("\n--- OPE on all benchmark rounds ---")
    print_table(results_all)

    regret_png = save_regret_curve(curves_eval, ARTIFACTS / "bandit_regret_curve.png")
    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "benchmark": bench_meta,
        "config": {
            "n_rounds": args.rounds, "k_arms": args.k, "train_frac": TRAIN_FRAC,
            "logging": {"epsilon_greedy_softmax": True, "eps": LOGGING_EPS, "temp": LOGGING_TEMP},
            "eval_temp": EVAL_TEMP,
            "neural_ucb": {"alpha": NEURAL_ALPHA, "temperature": NEURAL_TEMP, "epochs": NEURAL_EPOCHS, "batch": NEURAL_BATCH, "replay": True, "sherman_morrison": True},
            "neural_greedy_baseline": {"alpha": 0.0, "same_reward_net_as_neural_ucb": True, "note": "no exploration bonus"},
            "linucb": {"alpha": LIN_ALPHA, "temperature": LIN_TEMP},
        },
        "heldout_eval": {"n_rounds": len(eval_rounds), "policies": results_eval},
        "all_rounds": {"n_rounds": len(rounds), "policies": results_all},
        "artifacts": {
            "report_json": str(ARTIFACTS / "bandit_ope_report.json"),
            "regret_curve_png": str(regret_png) if regret_png else None,
        },
        "notes": "IPS/SNIPS with oracle true_means for expected reward & cumulative regret on realistic non-linear contextual benchmark.",
    }
    (ARTIFACTS / "bandit_ope_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"[bandit-ope] saved: {ARTIFACTS / 'bandit_ope_report.json'}")
    print(f"[bandit-ope] saved: {regret_png}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
