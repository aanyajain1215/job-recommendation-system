#!/usr/bin/env python
"""M0 evaluation (research-grade, non-saturated).

Compares 3 stages on a leak-free benchmark:
  (a) Off-the-shelf BAAI/bge-base-en-v1.5 (bi-encoder only)
  (b) Domain fine-tuned bi-encoder (ml/artifacts/biencoder_finetuned)
  (c) Two-stage: fine-tuned bi-encoder retrieval + fine-tuned cross-encoder reranking
      (ml/artifacts/cross_encoder_finetuned), including avg inference latency (ms/user)

Benchmark:
  - Held-out user split from embedding_pairs.jsonl (strict by profile_id, same
    80/20 seed logic as training => zero user overlap). Each held-out profile
    with positive pairs becomes a query (profile_text -> relevant job_ids).
  - Golden postings corpus (ml/data/golden/postings.jsonl) expanded as hard
    distractors and golden relevance queries included, yielding a larger, more
    discriminative retrieval/reranking setting.

Metrics: Recall@1, Recall@3, Recall@5, MRR@10, NDCG@10 (macro-averaged).
Saves: backend/ml/reports/m0_embedding_eval.json
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

GOLDEN = BACKEND_ROOT / "ml" / "data" / "golden"
ARTIFACTS = BACKEND_ROOT / "ml" / "artifacts"
DATASETS = BACKEND_ROOT / "ml" / "datasets"
REPORTS = BACKEND_ROOT / "ml" / "reports"
PAIRS_PATH = DATASETS / "embedding_pairs.jsonl"

SEED = 42
TRAIN_RATIO = 0.8
RERANK_TOP_N = 50  # candidates reranked by cross-encoder per query


# ----------------------------- IO / split ---------------------------------


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def split_profile_ids(profile_ids: list[str], train_ratio: float = TRAIN_RATIO, seed: int = SEED):
    ids = sorted(set(profile_ids))
    rng = random.Random(seed)
    rng.shuffle(ids)
    if len(ids) <= 1:
        return set(ids), set()
    n_train = max(1, int(round(len(ids) * train_ratio)))
    if n_train >= len(ids):
        n_train = len(ids) - 1
    return set(ids[:n_train]), set(ids[n_train:])


# ----------------------------- metrics ------------------------------------


def dcg_at_k(rels: list[float], k: int) -> float:
    s = 0.0
    for i, r in enumerate(rels[:k], start=1):
        s += (2.0 ** r - 1.0) / math.log2(i + 1)
    return s


def ndcg_at_k(ranked_labels: list[int], k: int) -> float:
    rels = [1.0 if x > 0 else 0.0 for x in ranked_labels[:k]]
    ideal = sorted(rels, reverse=True)
    # ideal over all relevant in list
    all_pos = sorted([1.0 if x > 0 else 0.0 for x in ranked_labels], reverse=True)
    idcg = dcg_at_k(all_pos[:k] if any(all_pos) else ideal, k)
    if idcg <= 0:
        return 0.0
    return dcg_at_k(rels, k) / idcg


def compute_metrics(ranked_doc_ids: list[str], relevant: set[str], k_values=(1, 3, 5)) -> dict:
    out = {}
    rel_flags = [1 if d in relevant else 0 for d in ranked_doc_ids]
    for k in k_values:
        topk = set(ranked_doc_ids[:k])
        out[f"recall@{k}"] = 1.0 if (topk & relevant) else 0.0 if relevant else 0.0
    # MRR@10
    mrr = 0.0
    for i, d in enumerate(ranked_doc_ids[:10], start=1):
        if d in relevant:
            mrr = 1.0 / i
            break
    out["mrr@10"] = mrr
    out["ndcg@10"] = ndcg_at_k(rel_flags, 10)
    return out


def average_metrics(per_query: list[dict]) -> dict:
    if not per_query:
        return {}
    keys = per_query[0].keys()
    return {k: round(sum(m[k] for m in per_query) / len(per_query), 6) for k in keys}


# ----------------------------- benchmark ----------------------------------


def build_benchmark():
    pairs = read_jsonl(PAIRS_PATH)
    postings = read_jsonl(GOLDEN / "postings.jsonl")
    golden_queries = read_jsonl(GOLDEN / "relevance_pairs.jsonl")

    # corpus: golden postings + all jobs seen in pairs (hard distractors/real jobs)
    doc_texts: dict[str, str] = {}
    doc_meta: dict[str, dict] = {}
    for row in postings:
        did = str(row.get("external_id"))
        text = f"{row.get('title','')}\n{row.get('description','')}".strip()
        if did and text:
            doc_texts[did] = text[:3000]
            doc_meta[did] = {"source": "golden", "domain": row.get("_domain")}
    for r in pairs:
        jid = str(r.get("job_id") or "")
        jt = str(r.get("job_text") or "").strip()
        if jid and jt and jid not in doc_texts:
            doc_texts[jid] = jt[:3000]
            doc_meta[jid] = {"source": "pairs"}

    # held-out user split from pairs (same rule as training)
    profile_ids = [str(r.get("profile_id") or "") for r in pairs if r.get("profile_id")]
    _train_p, val_p = split_profile_ids(profile_ids, TRAIN_RATIO, SEED)

    # held-out profile queries: profile_text -> positive job_ids in corpus
    pos_by_profile: dict[str, dict] = {}
    for r in pairs:
        pid = str(r.get("profile_id") or "")
        if pid not in val_p:
            continue
        if int(r.get("label", 0)) != 1:
            continue
        jid = str(r.get("job_id") or "")
        if not jid or jid not in doc_texts:
            continue
        entry = pos_by_profile.setdefault(pid, {"text": str(r.get("profile_text") or "").strip(), "relevant": set()})
        if not entry["text"]:
            entry["text"] = str(r.get("profile_text") or "").strip()
        entry["relevant"].add(jid)

    queries = []
    for pid, info in sorted(pos_by_profile.items()):
        if info["text"] and info["relevant"]:
            queries.append({"id": f"heldout:{pid}", "type": "heldout_user", "text": info["text"][:4000], "relevant": sorted(info["relevant"])})

    # golden queries (expanded corpus provides hard distractors)
    golden_index = {str(r.get("external_id")): i for i, r in enumerate(postings)}
    for q in golden_queries:
        rel = [j for j in q.get("relevant", []) if j in doc_texts]
        if rel:
            queries.append({
                "id": f"golden:{q.get('id')}",
                "type": "golden",
                "text": str(q.get("query") or ""),
                "relevant": rel,
            })

    if not doc_texts or not queries:
        raise SystemExit("Benchmark could not be built (missing pairs/golden data or held-out positives)")

    doc_ids = list(doc_texts.keys())
    doc_list = [doc_texts[d] for d in doc_ids]
    return {
        "doc_ids": doc_ids,
        "doc_texts": doc_list,
        "queries": queries,
        "val_profiles": sorted(val_p),
        "train_profiles": sorted(set(profile_ids) - val_p),
        "corpus_size": len(doc_ids),
        "golden_postings": len(postings),
        "pairs_total": len(pairs),
    }


# ----------------------------- encoding/scoring ---------------------------


def encode_texts(model, texts: list[str], batch_size: int = 32) -> np.ndarray:
    vecs = model.encode(texts, batch_size=batch_size, normalize_embeddings=True, show_progress_bar=False, convert_to_numpy=True)
    return np.asarray(vecs, dtype=np.float32)


def evaluate_biencoder(model, bench, label: str, batch_size: int = 32) -> dict:
    q_texts = [q["text"] for q in bench["queries"]]
    d_texts = bench["doc_texts"]
    doc_ids = bench["doc_ids"]

    t0 = time.perf_counter()
    q_vecs = encode_texts(model, q_texts, batch_size=batch_size)
    t_q = time.perf_counter() - t0

    t1 = time.perf_counter()
    d_vecs = encode_texts(model, d_texts, batch_size=batch_size)
    t_d = time.perf_counter() - t1

    sims = q_vecs @ d_vecs.T  # cosine on normalized
    per_query = []
    for i, q in enumerate(bench["queries"]):
        order = np.argsort(-sims[i])
        ranked = [doc_ids[j] for j in order.tolist()]
        per_query.append(compute_metrics(ranked, set(q["relevant"])))

    metrics = average_metrics(per_query)
    return {
        "stage": label,
        "metrics": metrics,
        "num_queries": len(bench["queries"]),
        "timing_ms": {
            "encode_queries_total_ms": round(t_q * 1000, 3),
            "encode_corpus_total_ms": round(t_d * 1000, 3),
            "avg_query_encode_ms": round((t_q / max(1, len(q_texts))) * 1000, 3),
        },
    }


def evaluate_two_stage(bi_model, ce_model, bench, bi_batch: int = 32, ce_batch: int = 16, rerank_top_n: int = RERANK_TOP_N) -> dict:
    from sentence_transformers import CrossEncoder  # noqa: PLC0415

    q_texts = [q["text"] for q in bench["queries"]]
    d_texts = bench["doc_texts"]
    doc_ids = bench["doc_ids"]

    # corpus encoded once (retrieval index)
    t_c0 = time.perf_counter()
    d_vecs = encode_texts(bi_model, d_texts, batch_size=bi_batch)
    t_corpus = time.perf_counter() - t_c0

    ce = ce_model if isinstance(ce_model, CrossEncoder) else CrossEncoder(str(ce_model))

    per_query = []
    latencies = []
    top_n = max(10, min(int(rerank_top_n), len(doc_ids)))

    for i, q in enumerate(bench["queries"]):
        t0 = time.perf_counter()
        q_vec = encode_texts(bi_model, [q_texts[i]], batch_size=bi_batch)[0]
        sims = q_vec @ d_vecs.T
        cand_idx = np.argsort(-sims)[:top_n].tolist()
        cand_ids = [doc_ids[j] for j in cand_idx]
        pairs = [(q_texts[i], d_texts[j]) for j in cand_idx]
        ce_scores = ce.predict(pairs, batch_size=ce_batch, show_progress_bar=False)
        ce_scores = np.asarray(ce_scores, dtype=np.float32).reshape(-1)
        reranked = [cand_ids[j] for j in np.argsort(-ce_scores).tolist()]
        # append remaining retrieved-by-bi order not reranked? keep reranked prefix then rest
        reranked_set = set(reranked)
        full_ranked = reranked + [doc_ids[j] for j in np.argsort(-sims).tolist() if doc_ids[j] not in reranked_set]
        per_query.append(compute_metrics(full_ranked, set(q["relevant"])))
        latencies.append((time.perf_counter() - t0) * 1000.0)

    metrics = average_metrics(per_query)
    avg_ms = round(sum(latencies) / len(latencies), 3) if latencies else None
    return {
        "stage": "(c) Two-Stage: Fine-Tuned Bi-Encoder Retrieval + Fine-Tuned Cross-Encoder Reranking",
        "metrics": metrics,
        "num_queries": len(bench["queries"]),
        "timing_ms": {
            "encode_corpus_total_ms": round(t_corpus * 1000, 3),
            "avg_inference_latency_ms_per_user": avg_ms,
            "p50_latency_ms": round(float(np.percentile(latencies, 50)), 3) if latencies else None,
            "p95_latency_ms": round(float(np.percentile(latencies, 95)), 3) if latencies else None,
        },
        "config": {"rerank_top_n": top_n},
    }


# ----------------------------- reporting ----------------------------------


def fmt(v):
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:.4f}"
    return str(v)


def print_table(rows: list[dict]):
    cols = ["stage", "recall@1", "recall@3", "recall@5", "mrr@10", "ndcg@10", "avg_ms/user"]
    header = " | ".join([f"{c:>12}" for c in cols])
    sep = "-" * len(header)
    print("\n" + sep)
    print(header)
    print(sep)
    for r in rows:
        m = r.get("metrics", {})
        avg = r.get("timing_ms", {}).get("avg_inference_latency_ms_per_user")
        line = [
            f"{r.get('short','')[:12]:>12}",
            f"{fmt(m.get('recall@1')):>12}",
            f"{fmt(m.get('recall@3')):>12}",
            f"{fmt(m.get('recall@5')):>12}",
            f"{fmt(m.get('mrr@10')):>12}",
            f"{fmt(m.get('ndcg@10')):>12}",
            f"{fmt(avg):>12}",
        ]
        print(" | ".join(line))
    print(sep + "\n")


def main(argv: list[str] | None = None) -> int:
    global SEED, TRAIN_RATIO, RERANK_TOP_N
    ap = argparse.ArgumentParser(description="Evaluate M0: base vs fine-tuned bi-encoder vs bi+cross-encoder (rigorous)")
    ap.add_argument("--base-model", default="BAAI/bge-base-en-v1.5")
    ap.add_argument("--finetuned", default=str(ARTIFACTS / "biencoder_finetuned"))
    ap.add_argument("--cross-encoder", default=str(ARTIFACTS / "cross_encoder_finetuned"))
    ap.add_argument("--rerank-top-n", type=int, default=RERANK_TOP_N)
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--train-ratio", type=float, default=TRAIN_RATIO)
    ap.add_argument("--out", default=str(REPORTS / "m0_embedding_eval.json"))
    args = ap.parse_args(argv)

    SEED = args.seed
    TRAIN_RATIO = args.train_ratio
    RERANK_TOP_N = args.rerank_top_n

    bench = build_benchmark()
    print(json.dumps({
        "benchmark": {
            "corpus_size": bench["corpus_size"],
            "num_queries": len(bench["queries"]),
            "heldout_profiles": len(bench["val_profiles"]),
            "golden_postings": bench["golden_postings"],
            "pairs_total": bench["pairs_total"],
            "split": "profile_id_80_20_zero_overlap",
        }
    }, indent=2))

    from sentence_transformers import SentenceTransformer  # noqa: PLC0415

    print("[eval] stage (a) base bi-encoder...")
    base_model = SentenceTransformer(args.base_model)
    res_a = evaluate_biencoder(base_model, bench, "(a) Off-the-shelf BAAI/bge-base-en-v1.5 (Bi-Encoder only)")
    res_a["short"] = "(a) base"

    ft_path = Path(args.finetuned)
    if not ft_path.exists():
        raise SystemExit(f"Fine-tuned bi-encoder not found: {ft_path}")
    print("[eval] stage (b) fine-tuned bi-encoder...")
    ft_model = SentenceTransformer(str(ft_path))
    res_b = evaluate_biencoder(ft_model, bench, "(b) Domain Fine-Tuned Bi-Encoder")
    res_b["short"] = "(b) finetuned"

    ce_path = Path(args.cross_encoder)
    if not ce_path.exists():
        raise SystemExit(f"Fine-tuned cross-encoder not found: {ce_path}")
    print("[eval] stage (c) two-stage bi + cross-encoder reranking...")
    res_c = evaluate_two_stage(ft_model, str(ce_path), bench, rerank_top_n=args.rerank_top_n)
    res_c["short"] = "(c) bi+ce"

    rows = [res_a, res_b, res_c]
    print_table(rows)

    def deltas(base_m, other_m):
        keys = ["recall@1", "recall@3", "recall@5", "mrr@10", "ndcg@10"]
        return {k: round(float(other_m.get(k, 0.0)) - float(base_m.get(k, 0.0)), 6) for k in keys}

    improvements = {
        "b_vs_a": deltas(res_a["metrics"], res_b["metrics"]),
        "c_vs_a": deltas(res_a["metrics"], res_c["metrics"]),
        "c_vs_b": deltas(res_b["metrics"], res_c["metrics"]),
        "b_beats_a_ndcg10": res_b["metrics"]["ndcg@10"] > res_a["metrics"]["ndcg@10"],
        "c_beats_b_ndcg10": res_c["metrics"]["ndcg@10"] > res_b["metrics"]["ndcg@10"],
        "c_beats_a_ndcg10": res_c["metrics"]["ndcg@10"] > res_a["metrics"]["ndcg@10"],
    }

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "benchmark": {
            "corpus_size": bench["corpus_size"],
            "num_queries": len(bench["queries"]),
            "heldout_profiles": len(bench["val_profiles"]),
            "golden_postings": bench["golden_postings"],
            "pairs_total": bench["pairs_total"],
            "split": {"by": "profile_id", "train_ratio": TRAIN_RATIO, "seed": SEED, "zero_user_overlap": True},
            "expanded_with_hard_distractors": True,
        },
        "stages": {
            "a_base_biencoder": res_a,
            "b_finetuned_biencoder": res_b,
            "c_two_stage_bi_ce": res_c,
        },
        "comparison_table": [
            {"stage": r["stage"], **r["metrics"], **{k: v for k, v in r.get("timing_ms", {}).items()}} for r in rows
        ],
        "improvements": improvements,
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"report_saved: {out_path}")
    print("improvements: " + json.dumps(improvements, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
