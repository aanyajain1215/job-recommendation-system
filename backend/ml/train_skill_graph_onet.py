#!/usr/bin/env python
"""M1 skill graph: GraphSAGE trained on the real O*NET occupation-technology graph.

Replaces the earlier GNN, which trained on ~100 hand-written YAML lines and was
scored on transfer pairs generated from the same hand-made clusters (circular).

Graph   bipartite: 923 O*NET occupations <-> ~2.6k technologies ("uses" edges).
Model   2-layer GraphSAGE (mean aggregation), node features = BGE embeddings of
        occupation title+description and technology name, trained with BPR link
        prediction. CPU only (the laptop GPU is unstable under long loads).

Evaluation - everything below is held out from training:
  E1 link prediction  hide 20% of each occupation's technologies; rank all
                      technologies for the occupation; Recall@10/50, MRR, AUC.
  E2 skill adjacency  pair a skill the occupation kept with one that was hidden
                      (positive) vs one it never uses (negative); AUC of the
                      skill-skill cosine. Reported with easy negatives (any tool)
                      and hard negatives (tools used by occupations in the same
                      O*NET job group). Isotonic calibration is fitted on hard
                      validation pairs, so "related" must beat same-domain tools.
  E3 related jobs     do occupation embeddings recover O*NET's expert-curated
                      "related occupations" (never used in training)? Recall@10.
  E4 continuity       the old hand-written transfer_pairs.jsonl (labels came from
                      the generator's clusters - shown for comparison only).
Baselines: popularity, BGE zero-shot cosine, PPMI-SVD co-occurrence embeddings.

Outputs
  ml/artifacts/skill2vec_v{N}.joblib      vectors for every technology + app skill,
                                          with calibration (loaded by the app)
  ml/artifacts/skillgraph_gnn_v{N}.json   full report
  ml/artifacts/graphsage_loss_curve.{json,png}
"""

from __future__ import annotations

import os

os.environ["CUDA_VISIBLE_DEVICES"] = "-1"  # CPU only; must precede torch import

import argparse  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import random  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from collections import defaultdict  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from ml import onet  # noqa: E402
from ml.resume_jd_fit import CACHE_ROOT, use_project_cache  # noqa: E402

use_project_cache()

ARTIFACTS = BACKEND_ROOT / "ml" / "artifacts"
SEED = 42


def set_seed(seed: int) -> None:
    import torch  # noqa: PLC0415

    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


# --------------------------------------------------------------------------
# Data + split
# --------------------------------------------------------------------------

def split_edges(occ_techs: dict[str, set[str]], holdout: float, seed: int):
    """Per occupation, hide `holdout` of its technologies (1/4 val, 3/4 test).

    A technology's last remaining training edge is never hidden, so every node
    keeps at least one neighbour in the training graph.
    """
    rng = random.Random(seed)
    tech_deg = defaultdict(int)
    for ts in occ_techs.values():
        for t in ts:
            tech_deg[t] += 1
    train, val, test = defaultdict(set), defaultdict(set), defaultdict(set)
    for occ in sorted(occ_techs):
        techs = sorted(occ_techs[occ])
        rng.shuffle(techs)
        n_hold = int(round(len(techs) * holdout)) if len(techs) >= 4 else 0
        for t in techs:
            if n_hold > 0 and tech_deg[t] > 1:
                (val if rng.random() < 0.25 else test)[occ].add(t)
                tech_deg[t] -= 1
                n_hold -= 1
            else:
                train[occ].add(t)
    return dict(train), dict(val), dict(test)


def bge_features(texts: list[str], model_name: str) -> np.ndarray:
    key = hashlib.sha1(("\n".join(texts) + model_name).encode("utf-8")).hexdigest()[:16]
    path = CACHE_ROOT / f"onet_bge_{key}.npy"
    if path.exists():
        return np.load(path)
    from sentence_transformers import SentenceTransformer  # noqa: PLC0415

    model = SentenceTransformer(model_name, device="cpu")
    model.max_seq_length = 256
    t0 = time.perf_counter()
    X = model.encode(texts, batch_size=32, normalize_embeddings=True, show_progress_bar=False)
    print(f"[features] BGE-encoded {len(texts)} texts in {time.perf_counter() - t0:.0f}s")
    path.parent.mkdir(parents=True, exist_ok=True)
    np.save(path, X)
    return X


# --------------------------------------------------------------------------
# GraphSAGE (plain PyTorch, sparse mean aggregation)
# --------------------------------------------------------------------------

def build_sage(in_dim: int, hidden: int, out_dim: int, dropout: float):
    import torch  # noqa: PLC0415
    import torch.nn as nn  # noqa: PLC0415
    import torch.nn.functional as F  # noqa: PLC0415

    class GraphSAGE(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.inp = nn.Linear(in_dim, hidden)
            self.self1, self.neigh1 = nn.Linear(hidden, hidden), nn.Linear(hidden, hidden, bias=False)
            self.self2, self.neigh2 = nn.Linear(hidden, out_dim), nn.Linear(hidden, out_dim, bias=False)
            self.drop = nn.Dropout(dropout)

        def layers(self, X, A):
            h0 = self.drop(F.relu(self.inp(X)))
            h1 = self.drop(F.relu(self.self1(h0) + self.neigh1(torch.sparse.mm(A, h0))))
            h2 = self.self2(h1) + self.neigh2(torch.sparse.mm(A, h1))
            return h0, h1, F.normalize(h2, dim=-1)

        def forward(self, X, A):
            return self.layers(X, A)[2]


    return GraphSAGE()


def mean_adjacency(n_nodes: int, edges: list[tuple[int, int]]):
    import torch  # noqa: PLC0415

    src = [a for a, b in edges] + [b for a, b in edges]
    dst = [b for a, b in edges] + [a for a, b in edges]
    deg = np.bincount(np.asarray(src), minlength=n_nodes).astype(np.float32)
    vals = 1.0 / np.maximum(deg[np.asarray(src)], 1.0)
    idx = torch.tensor([src, dst], dtype=torch.long)
    return torch.sparse_coo_tensor(idx, torch.tensor(vals), (n_nodes, n_nodes)).coalesce()


def train_sage(X, n_occ, n_tech, train_edges, val_pos, cfg, log):
    import torch  # noqa: PLC0415
    import torch.nn.functional as F  # noqa: PLC0415

    N = n_occ + n_tech
    A = mean_adjacency(N, [(o, n_occ + t) for o, t in train_edges])
    Xt = torch.tensor(X, dtype=torch.float32)
    model = build_sage(X.shape[1], cfg["hidden"], cfg["out_dim"], cfg["dropout"])
    opt = torch.optim.Adam(model.parameters(), lr=cfg["lr"], weight_decay=cfg["weight_decay"])
    pos_o = torch.tensor([o for o, _ in train_edges])
    pos_t = torch.tensor([t for _, t in train_edges])
    g = torch.Generator().manual_seed(cfg["seed"])
    best = (-1.0, None, 0)
    for epoch in range(1, cfg["epochs"] + 1):
        model.train()
        z = model(Xt, A)
        zo, zt = z[:n_occ], z[n_occ:]
        k = cfg["negatives"]
        neg_t = torch.randint(0, n_tech, (len(pos_o) * k,), generator=g)
        s_pos = (zo[pos_o] * zt[pos_t]).sum(-1).repeat_interleave(k)
        s_neg = (zo[pos_o].repeat_interleave(k, 0) * zt[neg_t]).sum(-1)
        loss = -F.logsigmoid(cfg["temperature"] * (s_pos - s_neg)).mean()
        opt.zero_grad()
        loss.backward()
        opt.step()
        if epoch % 10 == 0 or epoch == 1:
            model.eval()
            with torch.no_grad():
                z = model(Xt, A).numpy()
            val_auc = pair_auc(z[:n_occ], z[n_occ:], val_pos, n_tech, seed=epoch)
            log.append({"epoch": epoch, "loss": float(loss.item()), "val_auc": val_auc})
            if val_auc > best[0]:
                best = (val_auc, {k_: v.clone() for k_, v in model.state_dict().items()}, epoch)
            if epoch - best[2] >= cfg["patience"]:
                break
    model.load_state_dict(best[1])
    model.eval()
    return model, Xt, A, best[2]


def pair_auc(zo, zt, pos_edges, n_tech, seed=0) -> float:
    from sklearn.metrics import roc_auc_score  # noqa: PLC0415

    rng = np.random.default_rng(seed)
    o = np.array([a for a, _ in pos_edges])
    t = np.array([b for _, b in pos_edges])
    tn = rng.integers(0, n_tech, len(o))
    s = np.concatenate([(zo[o] * zt[t]).sum(1), (zo[o] * zt[tn]).sum(1)])
    y = np.concatenate([np.ones(len(o)), np.zeros(len(o))])
    return float(roc_auc_score(y, s))


# --------------------------------------------------------------------------
# Baselines
# --------------------------------------------------------------------------

def ppmi_svd(train: dict[int, set[int]], n_tech: int, dim: int) -> np.ndarray:
    from scipy.sparse import csr_matrix  # noqa: PLC0415
    from sklearn.decomposition import TruncatedSVD  # noqa: PLC0415

    rows, cols = [], []
    for o, ts in train.items():
        for t in ts:
            rows.append(o)
            cols.append(t)
    M = csr_matrix((np.ones(len(rows)), (rows, cols)), shape=(max(train) + 1, n_tech))
    C = (M.T @ M).toarray()
    np.fill_diagonal(C, 0)
    total = C.sum()
    p_t = C.sum(1, keepdims=True) / max(total, 1)
    with np.errstate(divide="ignore", invalid="ignore"):
        pmi = np.log((C / max(total, 1)) / (p_t @ p_t.T))
    ppmi = np.nan_to_num(np.maximum(pmi, 0), posinf=0)
    V = TruncatedSVD(n_components=dim, random_state=SEED).fit_transform(ppmi)
    return V / np.maximum(np.linalg.norm(V, axis=1, keepdims=True), 1e-9)


def _norm(V):
    return V / np.maximum(np.linalg.norm(V, axis=1, keepdims=True), 1e-9)


# --------------------------------------------------------------------------
# Evaluation
# --------------------------------------------------------------------------

def eval_link_prediction(S: np.ndarray, train, held, exclude) -> dict:
    """S[occ, tech] scores. Rank all techs except the occupation's other known ones."""
    rec10, rec50, mrr, aucs = [], [], [], []
    for o, pos in held.items():
        if not pos:
            continue
        s = S[o].astype(np.float64).copy()
        mask = list(train.get(o, set()) | exclude.get(o, set()))
        s[mask] = -np.inf
        order = np.argsort(-s)
        rank = np.empty_like(order)
        rank[order] = np.arange(len(order))
        pos_ranks = np.sort(rank[list(pos)])
        n_cand = len(s) - len(mask)
        rec10.append(np.mean(pos_ranks < 10))
        rec50.append(np.mean(pos_ranks < 50))
        mrr.append(1.0 / (pos_ranks[0] + 1))
        n_neg = n_cand - len(pos)
        # AUC: share of negatives ranked below each positive
        below = [(n_cand - 1 - r) - (len(pos) - 1 - i) for i, r in enumerate(pos_ranks)]
        aucs.append(np.mean([b / n_neg for b in below]))
    return {"recall@10": round(float(np.mean(rec10)), 4), "recall@50": round(float(np.mean(rec50)), 4),
            "mrr": round(float(np.mean(mrr)), 4), "auc": round(float(np.mean(aucs)), 4),
            "occupations": len(rec10)}


def adjacency_pairs(train, held, n_tech, seed, group_pool=None, occ_group=None):
    """(a, b, label): a kept by the occupation, b hidden (1) or never used (0).

    With group_pool/occ_group, negatives are hard: tools used by other
    occupations in the same O*NET major group (e.g. 15-xxxx computing) that this
    occupation does not use. Falls back to a random tool when the pool is empty.
    """
    rng = random.Random(seed)
    out = []
    for o, pos in sorted(held.items()):
        kept = sorted(train.get(o, set()))
        if not kept:
            continue
        used = train.get(o, set()) | pos
        pool = sorted(group_pool[occ_group[o]] - used) if group_pool is not None else []
        for b in sorted(pos):
            a = rng.choice(kept)
            out.append((a, b, 1))
            if pool:
                nb = rng.choice(pool)
            else:
                while True:
                    nb = rng.randrange(n_tech)
                    if nb not in used:
                        break
            out.append((a, nb, 0))
    arr = np.asarray(out)
    return arr[:, :2], arr[:, 2]


def eval_adjacency(V: np.ndarray, pairs, labels) -> float:
    from sklearn.metrics import roc_auc_score  # noqa: PLC0415

    s = (V[pairs[:, 0]] * V[pairs[:, 1]]).sum(1)
    return round(float(roc_auc_score(labels, s)), 4)


def eval_related(Vo: np.ndarray, occ_codes: list[str], related: dict[str, list[str]]) -> dict:
    idx = {c: i for i, c in enumerate(occ_codes)}
    sims = Vo @ Vo.T
    np.fill_diagonal(sims, -np.inf)
    r10, r20 = [], []
    for c, rel in related.items():
        if c not in idx:
            continue
        gold = {idx[r] for r in rel if r in idx}
        if not gold:
            continue
        top = np.argsort(-sims[idx[c]])[:20]
        r10.append(len(gold & set(top[:10].tolist())) / min(len(gold), 10))
        r20.append(len(gold & set(top.tolist())) / min(len(gold), 20))
    return {"recall@10": round(float(np.mean(r10)), 4), "recall@20": round(float(np.mean(r20)), 4),
            "occupations": len(r10)}


def eval_old_pairs(vectors: dict[str, np.ndarray]) -> dict:
    from sklearn.metrics import roc_auc_score  # noqa: PLC0415

    path = BACKEND_ROOT / "ml" / "data" / "golden" / "transfer_pairs.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    s, y = [], []
    for r in rows:
        a, b = vectors.get(r["a"].lower()), vectors.get(r["b"].lower())
        if a is None or b is None:
            continue
        s.append(float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9)))
        y.append(int(bool(r["transferable"])))
    return {"auc": round(float(roc_auc_score(y, s)), 4) if len(set(y)) == 2 else None,
            "pairs_covered": len(y), "pairs_total": len(rows)}


# --------------------------------------------------------------------------
# Run
# --------------------------------------------------------------------------

def next_version(prefix: str) -> int:
    nums = []
    for p in ARTIFACTS.glob(f"{prefix}*.joblib"):
        try:
            nums.append(int(p.stem.replace(prefix, "")))
        except ValueError:
            pass
    return max(nums, default=0) + 1


def run(cfg: dict) -> dict:
    import joblib  # noqa: PLC0415
    import torch  # noqa: PLC0415
    from sklearn.linear_model import LogisticRegression  # noqa: PLC0415

    torch.set_num_threads(max(1, (os.cpu_count() or 2) // 2))  # gentle on the laptop
    set_seed(cfg["seed"])
    t_start = time.perf_counter()

    # ---- data
    vocab = onet.app_skill_vocabulary()
    all_techs = onet.load(min_degree=1).techs
    mapping_all = onet.map_app_skills(all_techs, vocab)
    data = onet.load(min_degree=cfg["min_degree"], keep=set(mapping_all.values()))
    occ_codes = sorted(data.occ_techs)
    techs = data.techs
    oi = {c: i for i, c in enumerate(occ_codes)}
    ti = {t: i for i, t in enumerate(techs)}
    n_occ, n_tech = len(occ_codes), len(techs)
    occ_techs = {oi[o]: {ti[t] for t in ts} for o, ts in data.occ_techs.items()}
    n_edges = sum(len(v) for v in occ_techs.values())
    print(f"[data] occupations={n_occ} technologies={n_tech} edges={n_edges}")

    train, val, test = split_edges(occ_techs, cfg["holdout"], cfg["seed"])
    train_edges = [(o, t) for o, ts in train.items() for t in ts]
    val_pos = [(o, t) for o, ts in val.items() for t in ts]
    print(f"[split] train={len(train_edges)} val={len(val_pos)} test={sum(len(v) for v in test.values())}")

    # ---- features
    occ_text = [f"{data.occupations[c]['title']}. {data.occupations[c]['description']}" for c in occ_codes]
    X = bge_features(occ_text + techs, cfg["bge_model"])
    Xo, Xt = X[:n_occ], X[n_occ:]

    # ---- GraphSAGE
    log: list[dict] = []
    t0 = time.perf_counter()
    model, X_t, A, best_epoch = train_sage(X, n_occ, n_tech, train_edges, val_pos, cfg, log)
    train_seconds = time.perf_counter() - t0
    with torch.no_grad():
        Z = model(X_t, A).numpy()
    Zo, Zt = Z[:n_occ], Z[n_occ:]
    print(f"[train] GraphSAGE best epoch {best_epoch}, {train_seconds:.0f}s")

    # ---- baselines
    V_ppmi = ppmi_svd(train, n_tech, cfg["out_dim"])
    Vo_ppmi = _norm(np.stack([V_ppmi[list(train[o])].mean(0) if o in train else np.zeros(cfg["out_dim"])
                              for o in range(n_occ)]))
    pop = np.zeros(n_tech)
    for ts in train.values():
        for t in ts:
            pop[t] += 1

    methods = {
        "Popularity (most-used tools)": (np.tile(pop, (n_occ, 1)), None, None),
        "BGE text similarity (zero-shot)": (Xo @ Xt.T, Xt, Xo),
        "PPMI-SVD co-occurrence": (Vo_ppmi @ V_ppmi.T, V_ppmi, Vo_ppmi),
        "GraphSAGE (this model)": (Zo @ Zt.T, Zt, Zo),
    }

    occ_group = {i: c[:2] for i, c in enumerate(occ_codes)}  # SOC major group
    group_pool: dict[str, set[int]] = defaultdict(set)
    for o, ts in train.items():
        group_pool[occ_group[o]] |= ts
    easy_test = adjacency_pairs(train, test, n_tech, cfg["seed"] + 1)
    adj_val_pairs, adj_val_y = adjacency_pairs(train, val, n_tech, cfg["seed"], group_pool, occ_group)
    adj_test_pairs, adj_test_y = adjacency_pairs(train, test, n_tech, cfg["seed"] + 1, group_pool, occ_group)

    results = {}
    for name, (S, V_t, V_o) in methods.items():
        res = {"E1_link_prediction_test": eval_link_prediction(S, train, test, val)}
        if V_t is not None:
            res["E2_skill_adjacency_auc_test"] = {
                "easy_negatives": eval_adjacency(V_t, *easy_test),
                "hard_negatives_same_job_group": eval_adjacency(V_t, adj_test_pairs, adj_test_y),
            }
            res["E3_related_occupations"] = eval_related(V_o, occ_codes, data.related)
        results[name] = res
        print(f"[eval] {name}: {json.dumps(res)}")

    # ---- calibration of GraphSAGE skill-skill cosine, fitted on VAL (hard) pairs.
    # Isotonic (monotone, piecewise) rather than Platt: Platt is a single logistic
    # in cosine and under-states the high end (said 0.74 where the held-out rate
    # was ~0.9). The app interpolates the stored breakpoints.
    from sklearn.isotonic import IsotonicRegression  # noqa: PLC0415

    cos_val = (Zt[adj_val_pairs[:, 0]] * Zt[adj_val_pairs[:, 1]]).sum(1)
    cos_test = (Zt[adj_test_pairs[:, 0]] * Zt[adj_test_pairs[:, 1]]).sum(1)

    def _cal_stats(p, y):
        bins = np.clip((p * 10).astype(int), 0, 9)
        ece = sum(abs(p[bins == k].mean() - y[bins == k].mean()) * (bins == k).mean()
                  for k in range(10) if (bins == k).any())
        out = {"brier": round(float(np.mean((p - y) ** 2)), 4), "ece": round(float(ece), 4)}
        for t in (0.65, cfg["min_prob"]):
            m = p >= t
            out[f"precision_at_p>={t}"] = round(float(y[m].mean()), 4) if m.any() else None
            out[f"share_of_true_pairs_kept_at_p>={t}"] = round(float(m[y == 1].mean()), 4)
        return out

    platt = LogisticRegression().fit(cos_val.reshape(-1, 1), adj_val_y)
    p_platt = platt.predict_proba(cos_test.reshape(-1, 1))[:, 1]
    iso = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip").fit(cos_val, adj_val_y)
    p_iso = iso.predict(cos_test)
    calibration = {
        "kind": "isotonic",
        "x": [round(float(v), 5) for v in iso.X_thresholds_],
        "y": [round(float(v), 5) for v in iso.y_thresholds_],
        "min_prob": cfg["min_prob"],
        "fitted_on": "validation adjacency pairs, hard (same-job-group) negatives",
        "test_isotonic": _cal_stats(p_iso, adj_test_y),
        "test_platt_for_comparison": _cal_stats(p_platt, adj_test_y),
        "min_cosine_for_evidence": round(float(np.interp(cfg["min_prob"], iso.y_thresholds_, iso.X_thresholds_)), 4),
    }
    print(f"[calibration] {json.dumps({k: v for k, v in calibration.items() if k not in ('x', 'y')})}")

    # ---- vectors for the app: every technology + every app skill
    vectors: dict[str, np.ndarray] = {t.lower(): Zt[i] for t, i in ti.items()}
    mapping = {s: t for s, t in mapping_all.items() if t in ti}
    for skill, tech in mapping.items():
        vectors[skill] = Zt[ti[tech]]
    # Skills with no O*NET equivalent get NO vector (see onet.py): an earlier
    # inductive attempt produced nonsense neighbours (fastapi -> bookkeeping).
    unmapped = [s for s in vocab if s not in mapping and s not in vectors]

    # ---- continuity with the old (circular) evaluation
    old_path = ARTIFACTS / "skill2vec_v6.joblib"
    e4 = {"new_graphsage": eval_old_pairs(vectors)}
    if old_path.exists():
        old = joblib.load(old_path).get("vectors", {})
        e4["old_yaml_gnn_v6"] = eval_old_pairs({k.lower(): np.asarray(v) for k, v in old.items()})
    e4["note"] = ("labels come from hand-made clusters in synthesize_corpus.py, which the old model "
                  "was trained on - not an independent test")

    # ---- save
    version = next_version("skill2vec_v")
    artifact = ARTIFACTS / f"skill2vec_v{version}.joblib"
    meta = {
        "version": f"v{version}",
        "model": "graphsage_onet",
        "source": f"O*NET {onet.ONET_VERSION} software_skills (USDOL/ETA, CC BY 4.0)",
        "dim": cfg["out_dim"],
        "calibration": calibration,
        "coverage": {"app_vocab": len(vocab), "mapped_to_onet": len(mapping), "no_vector": len(unmapped)},
        "trained_at": datetime.now(timezone.utc).isoformat(),
    }
    joblib.dump({"vectors": {k: v.astype(np.float32).tolist() for k, v in vectors.items()}, "meta": meta},
                artifact, compress=3)

    curve_json, curve_png = ARTIFACTS / "graphsage_loss_curve.json", ARTIFACTS / "graphsage_loss_curve.png"
    curve_json.write_text(json.dumps({"history": log}, indent=2), encoding="utf-8")
    try:
        import matplotlib  # noqa: PLC0415

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt  # noqa: PLC0415

        fig, ax1 = plt.subplots(figsize=(8, 4.5))
        ax1.plot([h["epoch"] for h in log], [h["loss"] for h in log], color="#2563eb", label="Train BPR loss")
        ax1.set_xlabel("Epoch")
        ax1.set_ylabel("BPR loss")
        ax1.grid(True, alpha=0.25)
        ax2 = ax1.twinx()
        ax2.plot([h["epoch"] for h in log], [h["val_auc"] for h in log], color="#16a34a",
                 linestyle="--", label="Val link AUC (held-out O*NET edges)")
        ax2.set_ylabel("AUC")
        ax2.axvline(best_epoch, color="#999", linewidth=0.8)
        fig.legend(loc="lower center", ncol=2, fontsize=8)
        ax1.set_title("M1 GraphSAGE on O*NET occupation-technology graph")
        fig.tight_layout(rect=(0, 0.06, 1, 1))
        fig.savefig(curve_png, dpi=170)
        plt.close(fig)
    except Exception as exc:  # noqa: BLE001
        print(f"[plot] skipped: {exc}")

    report = {
        "artifact": str(artifact.relative_to(BACKEND_ROOT)).replace("\\", "/"),
        "version": f"v{version}",
        "replaces": "skill2vec_v6 (GraphSAGE on hand-written families.yaml/skill_prereqs.yaml)",
        "data": {
            "source": meta["source"], "occupations": n_occ, "technologies": n_tech, "edges": n_edges,
            "split": {"train": len(train_edges), "val": len(val_pos), "test": sum(len(v) for v in test.values()),
                      "rule": f"{int(cfg['holdout'] * 100)}% of each occupation's technologies hidden"},
            "min_occupations_per_technology": cfg["min_degree"],
        },
        "config": cfg,
        "best_epoch": best_epoch,
        "train_seconds": round(train_seconds, 1),
        "total_seconds": round(time.perf_counter() - t_start, 1),
        "evaluation": results,
        "calibration": calibration,
        "E4_old_handmade_pairs": e4,
        "app_skill_coverage": {
            "vocab": len(vocab), "mapped_to_onet": len(mapping), "no_vector": len(unmapped),
            "mapped": mapping, "no_vector_skills": unmapped,
            "no_vector_note": "no O*NET equivalent; app falls back to curated prereq/transfer edges",
        },
        "history": log,
    }
    (ARTIFACTS / f"skillgraph_gnn_v{version}.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("evaluation", "calibration", "E4_old_handmade_pairs")}, indent=2))
    print(f"[done] wrote {artifact.name} ({len(vectors)} vectors)")
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Train the M1 GraphSAGE skill graph on O*NET")
    ap.add_argument("--epochs", type=int, default=400)
    ap.add_argument("--min-degree", type=int, default=2)
    ap.add_argument("--seed", type=int, default=SEED)
    a = ap.parse_args(argv)
    cfg = {
        "epochs": a.epochs, "min_degree": a.min_degree, "seed": a.seed,
        "holdout": 0.2, "hidden": 128, "out_dim": 64, "dropout": 0.2, "lr": 5e-3,
        "weight_decay": 1e-5, "negatives": 5, "temperature": 10.0, "patience": 60,
        "min_prob": 0.8, "bge_model": "BAAI/bge-base-en-v1.5",
    }
    run(cfg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
