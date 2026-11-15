#!/usr/bin/env python
"""M1 SkillGraph: PyTorch Relational GraphSAGE over directed Skill-Role-Project graph.

Inductive GNN encoder (heterogeneous directed graph) capturing multi-hop structural
dependencies (e.g. Python -> Pandas -> Data Analyst role).

- Nodes: Skill, Role, Project (typed, directed edges)
- Features: Skill node inputs X in R^(N x 768) from M0 fine-tuned BGE bi-encoder;
  Role/Project initial features are mean-pooled connected Skill embeddings.
- Model: 2-layer Relational GraphSAGE (768 -> 256 -> 64) with L2 normalization,
  ReLU, Dropout, and relation-type edge weighting.
- Training: contrastive link prediction (BCEWithLogitsLoss with negative edge
  sampling) on held-out graph edges (80% train / 20% val). Val edges removed
  from train message-passing graph to prevent leakage.
- Logs: epoch Train Loss, Val Loss, Link-Pred AUC-ROC.

Artifacts:
  ml/artifacts/skill2vec_v{N}.joblib        ({"vectors": {skill: vec64}, "meta": ...})
  ml/artifacts/skillgraph_gnn_v{N}.json     (training/graph report)
  ml/artifacts/graphsage_loss_curve.png     (train/val loss + val AUC)
  ml/artifacts/graphsage_loss_curve.json    (plot data)
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import numpy as np

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

ARTIFACTS = BACKEND_ROOT / "ml" / "artifacts"
DATA_DIR = BACKEND_ROOT / "ml" / "data"
FAMILIES_YAML = DATA_DIR / "families.yaml"
PREREQS_YAML = DATA_DIR / "skill_prereqs.yaml"

IN_DIM = 768
HIDDEN_DIM = 256
OUT_DIM = 64
DROPOUT = 0.2
LR = 1e-3
WEIGHT_DECAY = 1e-4
EPOCHS = 120
NEG_RATIO = 1.0  # negatives per positive (per split eval/train step sampling)
SEED = 42
TRAIN_EDGE_RATIO = 0.8
DEVICE_STR = "cpu"


def set_seed(seed: int = SEED) -> None:
    random.seed(seed)
    np.random.seed(seed)
    try:
        import torch

        torch.manual_seed(seed)
    except Exception:
        pass


def _norm_skill(name: str) -> str:
    return str(name or "").lower().strip()


def _skill_node(name: str) -> str:
    return f"skill::{_norm_skill(name)}"


def _role_node(name: str) -> str:
    return f"role::{str(name or '').lower().strip()}"


def _project_node(pid: str) -> str:
    return f"project::{str(pid)}"


@dataclass
class HeteroGraph:
    # adjacency: src -> list[(dst, edge_type, weight)]
    adj: dict[str, list[tuple[str, str, float]]]
    node_types: dict[str, str]  # node_id -> type

    def __init__(self):
        self.adj = defaultdict(list)
        self.node_types = {}

    def add_node(self, node_id: str, ntype: str) -> None:
        if node_id and node_id not in self.node_types:
            self.node_types[node_id] = ntype
            self.adj.setdefault(node_id, self.adj.get(node_id, []))

    def add_edge(self, src: str, dst: str, etype: str, weight: float = 1.0, src_type: str = "skill", dst_type: str = "skill") -> None:
        if not src or not dst or src == dst:
            return
        self.add_node(src, src_type)
        self.add_node(dst, dst_type)
        self.adj[src].append((dst, etype, float(weight)))

    def neighbors(self, node: str) -> list[tuple[str, str, float]]:
        return self.adj.get(node, [])

    def nodes(self) -> list[str]:
        return list(self.node_types.keys())


def load_families(path: Path) -> list[dict]:
    try:
        import yaml  # noqa: PLC0415
    except Exception:
        return []
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    return data if isinstance(data, list) else []


def load_skill_prereqs(path: Path) -> list[dict]:
    try:
        import yaml  # noqa: PLC0415
    except Exception:
        return []
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    return data if isinstance(data, list) else []


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                rows.append(json.loads(line))
            except Exception:
                pass
    return rows


def build_graph(include_db: bool = True) -> HeteroGraph:
    """Build heterogeneous directed Skill-Role-Project graph.
    NOTE: golden/transfer_pairs.jsonl is NEVER read here (test leakage prevention).
    """
    g = HeteroGraph()

    # 1) Skill-skill edges from curated prereqs
    for row in load_skill_prereqs(PREREQS_YAML):
        src = _skill_node(row.get("from", ""))
        dst = _skill_node(row.get("to", ""))
        etype = str(row.get("type", "prereq")).lower()
        w = float(row.get("weight", 1.0) or 1.0)
        if src and dst:
            g.add_edge(src, dst, etype, w, "skill", "skill")
            if etype == "transfer":
                g.add_edge(dst, src, etype, w, "skill", "skill")

    # 2) Role (job family) nodes/edges from families.yaml
    families = load_families(FAMILIES_YAML)
    for fam in families:
        rname = str(fam.get("name") or "").strip()
        if not rname:
            continue
        rn = _role_node(rname)
        g.add_node(rn, "role")
        core = [_norm_skill(s) for s in (fam.get("core_skills") or []) if _norm_skill(s)]
        for sk in core:
            sn = _skill_node(sk)
            g.add_edge(rn, sn, "requires_skill", 1.0, "role", "skill")
            g.add_edge(sn, rn, "used_in_role", 1.0, "skill", "role")
        for i, a in enumerate(core):
            for b in core[i + 1:]:
                sa, sb = _skill_node(a), _skill_node(b)
                g.add_edge(sa, sb, "co_core_skill", 0.9, "skill", "skill")
                g.add_edge(sb, sa, "co_core_skill", 0.9, "skill", "skill")
        parent = fam.get("parent")
        if parent:
            pn = _role_node(str(parent))
            g.add_edge(pn, rn, "parent_role", 1.0, "role", "role")
            g.add_edge(rn, pn, "child_role", 1.0, "role", "role")

    # 3) Golden postings as project/role-context nodes (enrichment, not transfer labels)
    postings = _read_jsonl(DATA_DIR / "golden" / "postings.jsonl")
    for row in postings:
        pid = str(row.get("external_id") or "")
        domain = str(row.get("_domain") or row.get("title") or "posting").strip().lower()
        if not pid:
            continue
        pn = _project_node(f"posting:{pid}")
        rn = _role_node(domain)
        g.add_node(pn, "project")
        g.add_node(rn, "role")
        g.add_edge(rn, pn, "has_project", 1.0, "role", "project")
        g.add_edge(pn, rn, "project_of_role", 1.0, "project", "role")
        try:
            from scripts.fetch_jobs_live import extract_skills, load_surface_pairs  # noqa: PLC0415

            skills = extract_skills(row.get("title", ""), row.get("description", ""), load_surface_pairs())
            names = [_norm_skill(n) for n, _req in skills if _norm_skill(n)]
        except Exception:
            names = []
        seen = set()
        uniq = []
        for n in names:
            if n not in seen:
                seen.add(n)
                uniq.append(n)
        names = uniq
        for sk in names:
            sn = _skill_node(sk)
            g.add_edge(pn, sn, "uses_skill", 1.0, "project", "skill")
            g.add_edge(sn, pn, "demonstrated_in_project", 1.0, "skill", "project")
            g.add_edge(rn, sn, "requires_skill", 0.8, "role", "skill")
            g.add_edge(sn, rn, "used_in_role", 0.8, "skill", "role")
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                sa, sb = _skill_node(a), _skill_node(b)
                g.add_edge(sa, sb, "co_used_in_project", 0.7, "skill", "skill")
                g.add_edge(sb, sa, "co_used_in_project", 0.7, "skill", "skill")

    # 4) Enrich from DB when available
    if include_db:
        try:
            from sqlalchemy import select
            from sqlalchemy.orm import selectinload

            from app.core.db import SessionLocal
            from app.models.job import Job
            from app.models.job_family import JobFamily
            from app.models.profile_entities import Project
            from app.models.skill import JobSkill, Skill
            from app.models.skill_graph import SkillEdge

            db = SessionLocal()
            try:
                fams = db.scalars(select(JobFamily)).all()
                for fam in fams:
                    rn = _role_node(fam.name)
                    g.add_node(rn, "role")
                    for sk in (fam.core_skills or []):
                        sn = _skill_node(sk)
                        g.add_edge(rn, sn, "requires_skill", 1.0, "role", "skill")
                        g.add_edge(sn, rn, "used_in_role", 1.0, "skill", "role")

                jobs = db.scalars(
                    select(Job).options(
                        selectinload(Job.skills).selectinload(JobSkill.skill),
                        selectinload(Job.family),
                    )
                ).all()
                for job in jobs:
                    fam = getattr(job, "family", None)
                    if fam and getattr(fam, "name", None):
                        rn = _role_node(fam.name)
                    else:
                        title = (getattr(job, "title", None) or "").strip()
                        if not title:
                            continue
                        rn = _role_node(title[:60])
                    g.add_node(rn, "role")
                    for js in (job.skills or []):
                        sk = getattr(getattr(js, "skill", None), "name", None)
                        if not sk:
                            continue
                        sn = _skill_node(sk)
                        w = 1.2 if getattr(js, "is_required", True) else 0.8
                        g.add_edge(rn, sn, "requires_skill", w, "role", "skill")
                        g.add_edge(sn, rn, "used_in_role", w, "skill", "role")

                projects = db.scalars(select(Project)).all()
                for proj in projects:
                    pn = _project_node(str(proj.id))
                    g.add_node(pn, "project")
                    for sk in (getattr(proj, "detected_skills", None) or []):
                        sn = _skill_node(sk)
                        if sn.endswith("::"):
                            continue
                        g.add_edge(pn, sn, "uses_skill", 1.0, "project", "skill")
                        g.add_edge(sn, pn, "demonstrated_in_project", 1.0, "skill", "project")

                all_skills = {s.id: s.name for s in db.scalars(select(Skill)).all()}
                for edge in db.scalars(select(SkillEdge)).all():
                    src_name = all_skills.get(edge.from_skill_id)
                    dst_name = all_skills.get(edge.to_skill_id)
                    if not src_name or not dst_name:
                        continue
                    et = edge.edge_type.value if hasattr(edge.edge_type, "value") else str(edge.edge_type)
                    g.add_edge(_skill_node(src_name), _skill_node(dst_name), et.lower(), float(edge.weight or 1.0), "skill", "skill")
            finally:
                db.close()
        except Exception as exc:
            print(f"[graphsage] DB enrichment skipped: {exc}", file=sys.stderr)

    return g


# --------------------------- features / tensors ----------------------------


def get_skill_bge_embeddings(skill_names: list[str]) -> np.ndarray:
    """768-d M0 fine-tuned BGE embeddings for skills (fallback to base if needed)."""
    texts = [f"Skill: {s}" for s in skill_names]
    try:
        from app.services.embeddings import get_embedder  # noqa: PLC0415

        vecs = get_embedder().encode(texts)
        return np.asarray(vecs, dtype=np.float32)
    except Exception as exc:
        print(f"[graphsage] BGE embedder unavailable ({exc}); falling back to random features")
        rng = np.random.default_rng(SEED)
        return rng.standard_normal((len(skill_names), IN_DIM), dtype=np.float32)


def build_features(g: HeteroGraph, node_index: dict[str, int]) -> np.ndarray:
    """X in R^(N,768): skill from M0 BGE; role/project mean-pooled from connected skills."""
    N = len(node_index)
    X = np.zeros((N, IN_DIM), dtype=np.float32)
    skills = [n for n, t in g.node_types.items() if t == "skill"]
    skill_names = [n.split("::", 1)[1] for n in skills]
    if skills:
        svecs = get_skill_bge_embeddings(skill_names)
        for n, v in zip(skills, svecs):
            X[node_index[n]] = v
    # role/project = mean of connected skill embeddings
    for n, t in g.node_types.items():
        if t == "skill":
            continue
        nbr_skill_vecs = []
        for dst, _et, _w in g.neighbors(n):
            if g.node_types.get(dst) == "skill":
                nbr_skill_vecs.append(X[node_index[dst]])
        # also check incoming
        # (graph adj is outgoing; scan a bit cheaply by checking nodes that point to n not stored; use reverse pass)
        if nbr_skill_vecs:
            X[node_index[n]] = np.mean(np.stack(nbr_skill_vecs, axis=0), axis=0)
    # reverse pass to catch roles/projects that only have incoming edges
    rev: dict[str, list[str]] = defaultdict(list)
    for src, nbrs in g.adj.items():
        for dst, _et, _w in nbrs:
            rev[dst].append(src)
    for n, t in g.node_types.items():
        if t == "skill":
            continue
        if np.linalg.norm(X[node_index[n]]) > 0:
            continue
        nbr_skill_vecs = [X[node_index[s]] for s in rev.get(n, []) if g.node_types.get(s) == "skill"]
        if nbr_skill_vecs:
            X[node_index[n]] = np.mean(np.stack(nbr_skill_vecs, axis=0), axis=0)
    # normalize rows
    norms = np.linalg.norm(X, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    X = X / norms
    return X.astype(np.float32)


def edge_list(g: HeteroGraph, node_index: dict[str, int], rel_index: dict[str, int]):
    """Unique directed edges as arrays (src,dst,rel,w)."""
    seen = set()
    srcs, dsts, rels, ws = [], [], [], []
    for s, nbrs in g.adj.items():
        if s not in node_index:
            continue
        for d, et, w in nbrs:
            if d not in node_index:
                continue
            key = (node_index[s], node_index[d], et)
            if key in seen:
                continue
            seen.add(key)
            srcs.append(node_index[s])
            dsts.append(node_index[d])
            rels.append(rel_index.setdefault(et, len(rel_index)))
            ws.append(float(w))
    return (
        np.array(srcs, dtype=np.int64),
        np.array(dsts, dtype=np.int64),
        np.array(rels, dtype=np.int64),
        np.array(ws, dtype=np.float32),
    )


def _auc_roc(y_true: np.ndarray, scores: np.ndarray) -> float:
    pos = scores[y_true == 1]
    neg = scores[y_true == 0]
    n_pos, n_neg = len(pos), len(neg)
    if n_pos == 0 or n_neg == 0:
        return 0.0
    order = np.argsort(scores)
    ranks = np.empty_like(order, dtype=np.float64)
    ranks[order] = np.arange(1, len(scores) + 1, dtype=np.float64)
    # tie correction
    sorted_scores = scores[order]
    i = 0
    while i < len(sorted_scores):
        j = i
        while j + 1 < len(sorted_scores) and sorted_scores[j + 1] == sorted_scores[i]:
            j += 1
        if j > i:
            avg = (i + 1 + j + 1) / 2.0
            ranks[order[i : j + 1]] = avg
        i = j + 1
    sum_pos_ranks = ranks[y_true == 1].sum()
    auc = (sum_pos_ranks - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg)
    return float(max(0.0, min(1.0, auc)))


# --------------------------- model ----------------------------------------


def train_graphsage(X_np: np.ndarray, edge_src, edge_dst, edge_rel, edge_w, rel_count: int, seed: int = SEED):
    import torch
    import torch.nn as nn
    import torch.nn.functional as F

    set_seed(seed)
    device = torch.device(DEVICE_STR)

    X = torch.tensor(X_np, dtype=torch.float32, device=device)
    N = X.shape[0]
    E = len(edge_src)

    rng = np.random.default_rng(seed)
    perm = rng.permutation(E)
    split = max(1, int(math.floor(E * TRAIN_EDGE_RATIO)))
    if split >= E:
        split = E - 1
    train_idx = perm[:split]
    val_idx = perm[split:]
    if len(val_idx) == 0:
        val_idx = train_idx[-max(1, len(train_idx)//5):]
        train_idx = train_idx[:-len(val_idx)] if len(train_idx) > len(val_idx) else train_idx

    def make_tensors(idxs):
        s = torch.tensor(edge_src[idxs], dtype=torch.long, device=device)
        d = torch.tensor(edge_dst[idxs], dtype=torch.long, device=device)
        r = torch.tensor(edge_rel[idxs], dtype=torch.long, device=device)
        w = torch.tensor(edge_w[idxs], dtype=torch.float32, device=device)
        return s, d, r, w

    tr_s, tr_d, tr_r, tr_w = make_tensors(train_idx)
    va_s, va_d, va_r, va_w = make_tensors(val_idx)

    # adjacency for message passing uses TRAIN edges only (leakage-safe)
    msg_src, msg_dst, msg_rel, msg_w = tr_s, tr_d, tr_r, tr_w

    # edge set for negative sampling checks (all known edges)
    all_edge_set = set(zip(edge_src.tolist(), edge_dst.tolist()))

    class RelGraphSAGELayer(nn.Module):
        def __init__(self, in_dim, out_dim, num_rels, dropout=0.0, activate=True):
            super().__init__()
            self.num_rels = num_rels
            self.self_lin = nn.Linear(in_dim, out_dim, bias=False)
            self.rel_lins = nn.ModuleList([nn.Linear(in_dim, out_dim, bias=False) for _ in range(num_rels)])
            self.rel_alpha = nn.Parameter(torch.ones(num_rels))
            self.dropout = nn.Dropout(dropout)
            self.activate = activate

        def forward(self, h, src, dst, rel, w):
            Nn = h.shape[0]
            agg = torch.zeros((Nn, self.self_lin.out_features), device=h.device, dtype=h.dtype)
            deg = torch.zeros((Nn, 1), device=h.device, dtype=h.dtype)
            for rid in range(self.num_rels):
                mask = (rel == rid)
                if not torch.any(mask):
                    continue
                s = src[mask]
                d = dst[mask]
                ew = w[mask].unsqueeze(-1)
                msg = self.rel_lins[rid](h[s]) * ew * self.rel_alpha[rid]
                agg.index_add_(0, d, msg)
                deg.index_add_(0, d, ew)
            deg = torch.clamp(deg, min=1.0)
            out = self.self_lin(h) + (agg / deg)
            if self.activate:
                out = F.relu(out)
            out = self.dropout(out)
            return out

    class RelGraphSAGE(nn.Module):
        def __init__(self, in_dim, hidden_dim, out_dim, num_rels, dropout=0.0):
            super().__init__()
            self.layer1 = RelGraphSAGELayer(in_dim, hidden_dim, num_rels, dropout=dropout, activate=True)
            self.layer2 = RelGraphSAGELayer(hidden_dim, out_dim, num_rels, dropout=0.0, activate=False)

        def forward(self, x, src, dst, rel, w):
            h = self.layer1(x, src, dst, rel, w)
            h = self.layer2(h, src, dst, rel, w)
            h = F.normalize(h, p=2, dim=-1)
            return h

    model = RelGraphSAGE(IN_DIM, HIDDEN_DIM, OUT_DIM, max(1, rel_count), dropout=DROPOUT).to(device)
    opt = torch.optim.Adam(model.parameters(), lr=LR, weight_decay=WEIGHT_DECAY)
    bce = nn.BCEWithLogitsLoss()

    def sample_neg(num, existing_set):
        neg_s = []
        neg_d = []
        tries = 0
        needed = int(num)
        while len(neg_s) < needed and tries < needed * 30 + 1000:
            tries += 1
            a = int(rng.integers(0, N))
            b = int(rng.integers(0, N))
            if a == b:
                continue
            if (a, b) in existing_set:
                continue
            neg_s.append(a)
            neg_d.append(b)
        if not neg_s:
            neg_s = [0]
            neg_d = [min(1, N - 1)]
        return torch.tensor(neg_s, dtype=torch.long, device=device), torch.tensor(neg_d, dtype=torch.long, device=device)

    def score_pairs(z, s, d):
        # dot-product logits (works well with L2-normalized embeddings)
        return (z[s] * z[d]).sum(dim=-1)

    history = []
    best_auc = -1.0
    best_state = None

    for epoch in range(1, EPOCHS + 1):
        model.train()
        z = model(X, msg_src, msg_dst, msg_rel, msg_w)

        pos_logits = score_pairs(z, tr_s, tr_d)
        neg_s, neg_d = sample_neg(max(1, int(len(tr_s) * NEG_RATIO)), all_edge_set)
        neg_logits = score_pairs(z, neg_s, neg_d)

        logits = torch.cat([pos_logits, neg_logits], dim=0)
        labels = torch.cat([torch.ones_like(pos_logits), torch.zeros_like(neg_logits)], dim=0)
        loss = bce(logits, labels)

        opt.zero_grad()
        loss.backward()
        opt.step()

        model.eval()
        with torch.no_grad():
            z_eval = model(X, msg_src, msg_dst, msg_rel, msg_w)
            v_pos = score_pairs(z_eval, va_s, va_d)
            vn_s, vn_d = sample_neg(max(1, int(len(va_s) * NEG_RATIO)), all_edge_set)
            v_neg = score_pairs(z_eval, vn_s, vn_d)
            v_logits = torch.cat([v_pos, v_neg], dim=0)
            v_labels = torch.cat([torch.ones_like(v_pos), torch.zeros_like(v_neg)], dim=0)
            v_loss = bce(v_logits, v_labels)
            scores = torch.sigmoid(v_logits).detach().cpu().numpy()
            yv = v_labels.detach().cpu().numpy().astype(np.int64)
            auc = _auc_roc(yv, scores)

        rec = {
            "epoch": epoch,
            "train_loss": float(loss.item()),
            "val_loss": float(v_loss.item()),
            "val_auc_roc": float(auc),
        }
        history.append(rec)
        if auc >= best_auc:
            best_auc = auc
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}

        if epoch == 1 or epoch % 10 == 0 or epoch == EPOCHS:
            print(
                f"[graphsage] epoch {epoch:03d}/{EPOCHS} "
                f"train_loss={rec['train_loss']:.4f} val_loss={rec['val_loss']:.4f} val_auc_roc={rec['val_auc_roc']:.4f}"
            )

    if best_state is not None:
        model.load_state_dict(best_state)
    model.eval()
    with torch.no_grad():
        Z = model(X, msg_src, msg_dst, msg_rel, msg_w).detach().cpu().numpy().astype(np.float32)
    # ensure L2 normalized
    zn = np.linalg.norm(Z, axis=1, keepdims=True)
    zn[zn == 0] = 1.0
    Z = Z / zn
    return Z, history, {
        "best_val_auc_roc": float(best_auc),
        "train_edges": int(len(train_idx)),
        "val_edges": int(len(val_idx)),
    }


def save_loss_curve(history: list[dict], out_json: Path, out_png: Path):
    out_json.write_text(json.dumps({"history": history}, indent=2), encoding="utf-8")
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt  # noqa: PLC0415

        epochs = [h["epoch"] for h in history]
        tr = [h["train_loss"] for h in history]
        va = [h["val_loss"] for h in history]
        auc = [h["val_auc_roc"] for h in history]
        fig, ax1 = plt.subplots(figsize=(8, 4.5))
        ax1.plot(epochs, tr, label="Train Loss", color="#2563eb", linewidth=1.6)
        ax1.plot(epochs, va, label="Val Loss", color="#dc2626", linewidth=1.6)
        ax1.set_xlabel("Epoch")
        ax1.set_ylabel("BCE Loss")
        ax1.grid(True, alpha=0.25)
        ax2 = ax1.twinx()
        ax2.plot(epochs, auc, label="Val AUC-ROC", color="#16a34a", linewidth=1.4, linestyle="--")
        ax2.set_ylabel("AUC-ROC")
        ax2.set_ylim(0.0, 1.05)
        lines, labels = ax1.get_legend_handles_labels()
        lines2, labels2 = ax2.get_legend_handles_labels()
        ax1.legend(lines + lines2, labels + labels2, loc="best")
        ax1.set_title("M1 Relational GraphSAGE: Link Prediction (Train/Val Loss, Val AUC-ROC)")
        fig.tight_layout()
        out_png.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(out_png, dpi=170)
        plt.close(fig)
        return str(out_png)
    except Exception as exc:
        print(f"[graphsage] plot failed: {exc}")
        return None


# --------------------------- artifact helpers -----------------------------


def extract_skill_vectors(g: HeteroGraph, node_index: dict[str, int], Z: np.ndarray) -> dict[str, list[float]]:
    out: dict[str, list[float]] = {}
    for node, idx in node_index.items():
        if node.startswith("skill::"):
            skill = node.split("::", 1)[1]
            if skill:
                out[skill] = Z[idx].astype(float).tolist()
    return out


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    av = np.asarray(a, dtype=np.float64)
    bv = np.asarray(b, dtype=np.float64)
    na = np.linalg.norm(av)
    nb = np.linalg.norm(bv)
    if na <= 0 or nb <= 0:
        return 0.0
    return float(np.dot(av, bv) / (na * nb))


def next_version(prefix: str = "skill2vec_v") -> str:
    existing = sorted(ARTIFACTS.glob(f"{prefix}*.joblib"))
    highest = 0
    for path in existing:
        try:
            highest = max(highest, int(path.stem.split("_v")[-1]))
        except ValueError:
            continue
    return f"v{highest + 1}"


def load_artifact(path: Path | None = None) -> dict | None:
    import joblib  # noqa: PLC0415

    if path is None:
        candidates = sorted(ARTIFACTS.glob("skill2vec_v*.joblib"))
        if not candidates:
            candidates = sorted(ARTIFACTS.glob("skillgraph_gnn_v*.joblib"))
        if not candidates:
            return None
        path = candidates[-1]
    try:
        payload = joblib.load(path)
        if isinstance(payload, dict) and "vectors" in payload:
            return payload
    except Exception as exc:
        print(f"[graphsage] artifact load failed: {exc}", file=sys.stderr)
    return None


def _print_transfer_table(result: dict):
    rows = (result or {}).get("rows") or []
    if not rows:
        return
    print("\nM1 transfer evaluation (3 rows)")
    header = f"{'mode':55s} {'Precision':>10s} {'Recall':>10s} {'F1':>10s} {'AUC-ROC':>10s}"
    print("-" * len(header))
    print(header)
    print("-" * len(header))
    for r in rows:
        print(
            f"{r['name'][:55]:55s} {r['precision']:10.4f} {r['recall']:10.4f} {r['f1']:10.4f} {r['auc_roc']:10.4f}"
        )
    print("-" * len(header))


def run(register: bool = True, include_db: bool = True) -> dict:
    import joblib  # noqa: PLC0415

    set_seed(SEED)
    ARTIFACTS.mkdir(parents=True, exist_ok=True)

    print("[graphsage] building heterogeneous directed Skill-Role-Project graph...")
    g = build_graph(include_db=include_db)
    nodes = g.nodes()
    if not nodes:
        raise SystemExit("[graphsage] empty graph")
    node_index = {n: i for i, n in enumerate(sorted(nodes))}
    rel_index: dict[str, int] = {}
    edge_src, edge_dst, edge_rel, edge_w = edge_list(g, node_index, rel_index)
    skills = [n for n in nodes if n.startswith("skill::")]
    roles = [n for n in nodes if n.startswith("role::")]
    projects = [n for n in nodes if n.startswith("project::")]
    print(
        f"[graphsage] graph: nodes={len(nodes)} (skills={len(skills)}, roles={len(roles)}, projects={len(projects)}), "
        f"edges={len(edge_src)}, relations={len(rel_index)} {sorted(rel_index.keys())}"
    )
    if len(edge_src) < 4:
        raise SystemExit("[graphsage] not enough edges for train/val split")

    print("[graphsage] building node features (Skill from M0 BGE 768-d, Role/Project mean-pooled)...")
    X = build_features(g, node_index)

    print("[graphsage] training 2-layer Relational GraphSAGE (768->256->64), link prediction BCE w/ neg sampling...")
    Z, history, split_meta = train_graphsage(X, edge_src, edge_dst, edge_rel, edge_w, rel_count=len(rel_index), seed=SEED)

    curve_json = ARTIFACTS / "graphsage_loss_curve.json"
    curve_png = ARTIFACTS / "graphsage_loss_curve.png"
    curve_png_path = save_loss_curve(history, curve_json, curve_png)
    print(f"[graphsage] loss/auc curve json: {curve_json}")
    print(f"[graphsage] loss/auc curve png:  {curve_png_path}")

    skill_vectors = extract_skill_vectors(g, node_index, Z)
    print(f"[graphsage] embeddings: total_nodes={len(node_index)}, skills={len(skill_vectors)}, dim={OUT_DIM}")

    version = next_version("skill2vec_v")
    artifact_path = ARTIFACTS / f"skill2vec_{version}.joblib"
    meta = {
        "model": "relational_graphsage_gnn",
        "method": "2-layer PyTorch Relational GraphSAGE (768->256->64) over directed Skill-Role-Project graph, contrastive link prediction",
        "inductive": True,
        "feature_init": "Skill nodes from M0 fine-tuned BGE (768-d); Role/Project mean-pooled connected Skill embeddings",
        "graph": {
            "node_types": ["Skill", "Role", "Project"],
            "relation_types": sorted(rel_index.keys()),
            "nodes": len(nodes),
            "skills": len(skills),
            "roles": len(roles),
            "projects": len(projects),
            "edges": int(len(edge_src)),
        },
        "graphsage": {
            "in_dim": IN_DIM,
            "hidden_dim": HIDDEN_DIM,
            "out_dim": OUT_DIM,
            "dropout": DROPOUT,
            "lr": LR,
            "weight_decay": WEIGHT_DECAY,
            "epochs": EPOCHS,
            "neg_ratio": NEG_RATIO,
            "loss": "BCEWithLogitsLoss",
            "negative_sampling": True,
            "relation_weighting": True,
            "l2_normalized_output": True,
            "seed": SEED,
        },
        "split": {
            "train_edge_ratio": TRAIN_EDGE_RATIO,
            **split_meta,
            "val_edges_removed_from_train_message_passing": True,
        },
        "training_history": history,
        "best_val_auc_roc": split_meta.get("best_val_auc_roc"),
        "vocab_size": len(skill_vectors),
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "artifacts": {
            "loss_curve_json": str(curve_json),
            "loss_curve_png": str(curve_png_path) if curve_png_path else None,
        },
    }

    joblib.dump({"vectors": skill_vectors, "meta": meta, "node_index": node_index}, artifact_path)

    report = {
        "artifact": str(artifact_path),
        "version": version,
        "vocab_size": len(skill_vectors),
        "best_val_auc_roc": split_meta.get("best_val_auc_roc"),
        "loss_curve_png": str(curve_png_path) if curve_png_path else None,
        "meta": meta,
    }
    (ARTIFACTS / f"skillgraph_gnn_{version}.json").write_text(
        json.dumps({k: v for k, v in report.items() if k != "meta"}, indent=2, default=str),
        encoding="utf-8",
    )

    # M1 evaluation: 3-row table (YAML-only, Pure GraphSAGE, Hybrid)
    transfer_result = None
    try:
        from ml import evaluate as evaluate_mod  # noqa: PLC0415

        transfer_result = evaluate_mod.transfer_metrics(skill_vectors)
        report["transfer_eval"] = transfer_result
        _print_transfer_table(transfer_result)
        if register:
            try:
                import ml.ml_registry as registry  # noqa: PLC0415

                row = registry.register(
                    "skill2vec",
                    version,
                    str(artifact_path.relative_to(BACKEND_ROOT)),
                    transfer_result,
                    promote=True,
                )
                report["registry"] = row
            except Exception as exc:
                report["registry_error"] = str(exc)
                print(f"[graphsage] registry step failed: {exc}", file=sys.stderr)
    except Exception as exc:
        report["eval_error"] = str(exc)
        print(f"[graphsage] transfer eval failed: {exc}", file=sys.stderr)

    # compact stdout summary
    summary = {
        "artifact": str(artifact_path),
        "version": version,
        "vocab_size": len(skill_vectors),
        "best_val_auc_roc": split_meta.get("best_val_auc_roc"),
        "loss_curve_png": str(curve_png_path) if curve_png_path else None,
        "transfer_rows": (transfer_result or {}).get("rows"),
    }
    print(json.dumps(summary, indent=2, default=str))
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Train M1 Relational GraphSAGE (Skill-Role-Project GNN)")
    ap.add_argument("--no-register", action="store_true", help="skip model_registry write/eval registration")
    ap.add_argument("--no-db", action="store_true", help="build graph from YAML/golden data only")
    args = ap.parse_args(argv)
    run(register=not args.no_register, include_db=not args.no_db)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
