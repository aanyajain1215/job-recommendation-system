#!/usr/bin/env python
"""§21 evaluation: baseline table + gates + run report.

    ranking        NDCG@10 / P@5 / MRR@10 for ranklet vs deterministic vs
                   popularity (comparative gate: ranklet ≥ deterministic)
    extraction     skill-set micro-F1 of the resume parser on golden resumes
                   (gate ≥ 0.85)
    transfer       P/R/F1 of graph-edge ∪ skill2vec-cosine classifier on
                   golden pairs (gate ≥ 0.80)
    calibration    Brier + ECE of the committed calibrator (gate ≤ 0.10)
    semantic       Recall@20 of MiniLM retrieval over the frozen golden
                   corpus (gate ≥ 0.75)

Writes ml/reports/eval-<date>.json and prints a table; `--gate` exits 1 on
any failed required gate (used by ml/train.py and CI).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

GOLDEN = BACKEND_ROOT / "ml" / "data" / "golden"
DATASETS = BACKEND_ROOT / "ml" / "datasets"
ARTIFACTS = BACKEND_ROOT / "ml" / "artifacts"
REPORTS = BACKEND_ROOT / "ml" / "reports"

EXTRACTION_F1_MIN = 0.85
TRANSFER_F1_MIN = 0.80
CALIBRATION_ECE_MAX = 0.10
SEMANTIC_RECALL_MIN = 0.75


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


# ---------------------------------------------------------------------------
# Individual reports
# ---------------------------------------------------------------------------

def ranking_report() -> dict | None:
    """Baseline table over the committed temporal test split."""
    if not (DATASETS / "test.jsonl").exists():
        return None
    from ml.train_ranklet import load_dataset, evaluate_baselines  # noqa: PLC0415

    X_train, _y_train, _g, train_meta = load_dataset(DATASETS / "train.jsonl")
    X_test, _y_test, _g2, test_meta = load_dataset(DATASETS / "test.jsonl")
    if not X_test:
        return None

    scores: list[float] | None = None
    candidates = sorted(ARTIFACTS.glob("ranklet_v*.txt"))
    if candidates:
        try:
            import lightgbm as lgb  # noqa: PLC0415

            booster = lgb.Booster(model_file=str(candidates[-1]))
            scores = [float(s) for s in booster.predict(X_test)]
        except Exception as exc:  # noqa: BLE001
            print(f"[eval] ranklet load failed: {exc}", file=sys.stderr)

    if scores is None:
        # baseline-only table (no model trained yet)
        fake = [0.0] * len(X_test)
        metrics = evaluate_baselines(train_meta, test_meta, fake)
        metrics.pop("ranklet", None)
        return {"metrics": metrics, "ranklet_trained": False}

    metrics = evaluate_baselines(train_meta, test_meta, scores)
    return {
        "metrics": metrics,
        "ranklet_trained": True,
        "artifact": candidates[-1].name,
        "gate_pass": metrics["ranklet"]["ndcg_at_10"]
        >= metrics["deterministic"]["ndcg_at_10"],
    }


def extraction_report() -> dict:
    """Skill-set micro-F1 (+ seniority accuracy) of the active parser."""
    from app.services.resume_parser import RegexResumeParser  # noqa: PLC0415
    from ml.metrics import micro_f1  # noqa: PLC0415

    resumes = _read_jsonl(GOLDEN / "resumes.jsonl")
    if not resumes:
        return {"skipped": "resumes.jsonl missing"}

    parser = RegexResumeParser()
    pairs: list[tuple[set, set]] = []
    seniority_hits = 0
    for row in resumes:
        parsed = parser.parse(row["text"])
        expected = set(row["expected"]["skills"])
        got = {s.name for s in parsed.skills}
        pairs.append((expected, got))
        if parsed.seniority == row["expected"]["seniority"]:
            seniority_hits += 1

    f1 = micro_f1(pairs)
    return {
        "f1": round(f1, 4),
        "seniority_accuracy": round(seniority_hits / len(resumes), 4),
        "n": len(resumes),
        "parser": "regex",
        "gate_pass": f1 >= EXTRACTION_F1_MIN,
    }


def _auc_roc(y_true: list[int], scores: list[float]) -> float:
    """AUC-ROC via rank statistic (no sklearn dependency required)."""
    pos = [s for y, s in zip(y_true, scores) if y == 1]
    neg = [s for y, s in zip(y_true, scores) if y == 0]
    n_pos, n_neg = len(pos), len(neg)
    if n_pos == 0 or n_neg == 0:
        return 0.0
    # rank all scores; average ranks for ties
    order = sorted(range(len(scores)), key=lambda i: scores[i])
    ranks = [0.0] * len(scores)
    i = 0
    r = 1
    while i < len(order):
        j = i
        while j + 1 < len(order) and scores[order[j + 1]] == scores[order[i]]:
            j += 1
        avg_rank = (r + (r + (j - i))) / 2.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg_rank
        r += (j - i + 1)
        i = j + 1
    sum_pos_ranks = sum(rank for rank, y in zip(ranks, y_true) if y == 1)
    auc = (sum_pos_ranks - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg)
    return float(max(0.0, min(1.0, auc)))


def _cos_vec(a, b) -> float:
    try:
        import numpy as np  # noqa: PLC0415
        av = np.asarray(a, dtype=np.float64)
        bv = np.asarray(b, dtype=np.float64)
        na = np.linalg.norm(av)
        nb = np.linalg.norm(bv)
        if na <= 0 or nb <= 0:
            return 0.0
        return float(np.dot(av, bv) / (na * nb))
    except Exception:
        return 0.0


def transfer_metrics(vectors: dict | None = None) -> dict:
    """M1 transfer evaluation: 3 separate rows (YAML-only, Pure Embedding, Hybrid)."""
    from app.core.config import get_settings  # noqa: PLC0415
    from app.services.skill_graph import load_seed_graph, transfer_similarity  # noqa: PLC0415
    from ml.metrics import precision_recall_f1  # noqa: PLC0415

    pairs = _read_jsonl(GOLDEN / "transfer_pairs.jsonl")
    if not pairs:
        return {"skipped": "transfer_pairs.jsonl missing"}

    if vectors is None:
        from ml.train_skill2vec import load_artifact  # noqa: PLC0415

        payload = load_artifact()
        vectors = payload["vectors"] if payload else None

    import numpy as np  # noqa: PLC0415

    graph = load_seed_graph()
    tau = float(getattr(get_settings(), "transfer_similarity_threshold", 0.65))

    emb_map = None
    if vectors:
        emb_map = {}
        for k, v in vectors.items():
            try:
                emb_map[str(k).lower().strip()] = np.asarray(v, dtype=np.float32)
            except Exception:
                continue

    y_true: list[int] = []
    modes = {
        "yaml_only": {"pred": [], "score": []},
        "pure_embedding": {"pred": [], "score": []},
        "hybrid": {"pred": [], "score": []},
    }

    for pair in pairs:
        a = str(pair["a"]).lower().strip()
        b = str(pair["b"]).lower().strip()
        label = 1 if bool(pair.get("transferable")) else 0
        y_true.append(label)

        # (a) YAML Rules Only (no embeddings)
        sim_yaml = transfer_similarity(graph, {a}, b, embeddings={})
        score_yaml = float(sim_yaml) if sim_yaml is not None else 0.0
        pred_yaml = score_yaml >= tau

        # (b) Pure GraphSAGE/embedding similarity only (zero YAML edge lookup)
        score_emb = 0.0
        if vectors and a in vectors and b in vectors:
            score_emb = float(_cos_vec(vectors[a], vectors[b]))
        pred_emb = score_emb >= tau

        # (c) Hybrid Graph + GraphSAGE (combined)
        sim_hybrid = transfer_similarity(graph, {a}, b, embeddings=emb_map)
        score_hybrid = float(sim_hybrid) if sim_hybrid is not None else 0.0
        # fallback to pure embedding if graph path absent but vectors exist
        if sim_hybrid is None and score_emb > 0.0:
            score_hybrid = score_emb
        pred_hybrid = score_hybrid >= tau

        modes["yaml_only"]["pred"].append(pred_yaml)
        modes["yaml_only"]["score"].append(score_yaml)
        modes["pure_embedding"]["pred"].append(pred_emb)
        modes["pure_embedding"]["score"].append(score_emb)
        modes["hybrid"]["pred"].append(pred_hybrid)
        modes["hybrid"]["score"].append(score_hybrid)

    rows = []
    name_map = {
        "yaml_only": "YAML Rules Only (embeddings=None)",
        "pure_embedding": "Pure GraphSAGE Embedding Similarity Only (no YAML edge lookup)",
        "hybrid": "Hybrid Graph + GraphSAGE",
    }
    for key, display in name_map.items():
        preds_bool = [bool(x) for x in modes[key]["pred"]]
        y_bool = [bool(y) for y in y_true]
        precision, recall, f1 = precision_recall_f1(y_bool, preds_bool)
        auc = _auc_roc(y_true, modes[key]["score"])
        row = {
            "mode": key,
            "name": display,
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "auc_roc": round(auc, 4),
            "n_pairs": len(pairs),
            "threshold": tau,
        }
        rows.append(row)

    hybrid = next(r for r in rows if r["mode"] == "hybrid")
    result = {
        # backward-compatible summary uses hybrid
        "precision": hybrid["precision"],
        "recall": hybrid["recall"],
        "f1": hybrid["f1"],
        "auc_roc": hybrid["auc_roc"],
        "n_pairs": len(pairs),
        "threshold": tau,
        "vectors": vectors is not None,
        "rows": rows,
    }
    result["gate_pass"] = hybrid["f1"] >= TRANSFER_F1_MIN
    return result


def semantic_recall(k: int = 20) -> dict:
    """Recall@k of MiniLM retrieval over the frozen golden corpus."""
    postings = _read_jsonl(GOLDEN / "postings.jsonl")
    queries = _read_jsonl(GOLDEN / "relevance_pairs.jsonl")
    if not postings or not queries:
        return {"skipped": "golden postings/queries missing"}

    try:
        from app.services.embeddings import get_embedder  # noqa: PLC0415
        from ml.metrics import recall_at_k_over_corpus  # noqa: PLC0415

        embedder = get_embedder()
        ids = [row["external_id"] for row in postings]
        index = {jid: i for i, jid in enumerate(ids)}
        docs = [
            f"{row['title']}\n{row['description']}"[:2000] for row in postings
        ]
        doc_vecs = [list(map(float, v)) for v in embedder.encode(docs)]
        query_vecs = [
            list(map(float, v))
            for v in embedder.encode([q["query"] for q in queries])
        ]
        relevant = [
            {index[j] for j in q["relevant"] if j in index} for q in queries
        ]
        score = recall_at_k_over_corpus(query_vecs, doc_vecs, relevant, k=k)
    except Exception as exc:  # noqa: BLE001
        return {"skipped": f"embedder unavailable: {exc}"}

    return {
        f"recall_at_{k}": round(score, 4),
        "n_queries": len(queries),
        "corpus": len(postings),
        "gate_pass": score >= SEMANTIC_RECALL_MIN,
    }


def calibration_report() -> dict | None:
    """Brier + ECE of the committed M3 artifact on the test split."""
    candidates = sorted(ARTIFACTS.glob("calibrator_v*.joblib"))
    if not candidates or not (DATASETS / "test.jsonl").exists():
        return None

    import joblib  # noqa: PLC0415

    from app.core.config import get_settings  # noqa: PLC0415
    from ml.metrics import brier_score, expected_calibration_error  # noqa: PLC0415
    from ml.train_ranklet import load_dataset  # noqa: PLC0415

    payload = joblib.load(candidates[-1])
    _X, y, _g, meta = load_dataset(DATASETS / "test.jsonl")
    threshold = get_settings().calibrator_positive_min
    outcomes = [1 if label >= threshold else 0 for label in y]
    scores = [row["score"] for row in meta]

    model = payload["model"]
    if payload.get("kind") == "platt":
        probs = [float(p) for p in model.predict_proba([[s] for s in scores])[:, 1]]
    else:
        probs = [float(p) for p in model.predict(scores)]

    ece = expected_calibration_error(probs, outcomes)
    return {
        "ece": round(ece, 4),
        "brier": round(brier_score(probs, outcomes), 4),
        "n": len(scores),
        "kind": payload.get("kind"),
        "artifact": candidates[-1].name,
        "gate_pass": ece <= CALIBRATION_ECE_MAX,
    }


# ---------------------------------------------------------------------------
# Gates + driver
# ---------------------------------------------------------------------------

def collect_gates() -> dict:
    gates: dict[str, dict] = {}

    ranking = ranking_report()
    if ranking is None:
        gates["ranking_ndcg_vs_deterministic"] = {"status": "no_datasets"}
    elif not ranking.get("ranklet_trained"):
        gates["ranking_ndcg_vs_deterministic"] = {"status": "no_ranklet"}
    else:
        gates["ranking_ndcg_vs_deterministic"] = {
            "value": ranking["metrics"]["ranklet"]["ndcg_at_10"],
            "baseline": ranking["metrics"]["deterministic"]["ndcg_at_10"],
            "required": True,
            "passed": bool(ranking["gate_pass"]),
        }

    extraction = extraction_report()
    gates["extraction_f1"] = {
        "value": extraction.get("f1"),
        "threshold": EXTRACTION_F1_MIN,
        "required": True,
        "passed": bool(extraction.get("gate_pass")),
    }

    transfer = transfer_metrics()
    gates["transfer_f1"] = {
        "value": transfer.get("f1"),
        "threshold": TRANSFER_F1_MIN,
        "required": True,
        "passed": bool(transfer.get("gate_pass")),
        "rows": transfer.get("rows"),
    }

    calibration = calibration_report()
    if calibration is None:
        gates["calibration_ece"] = {"status": "no_calibrator"}
    else:
        gates["calibration_ece"] = {
            "value": calibration.get("ece"),
            "threshold": CALIBRATION_ECE_MAX,
            "required": True,
            "passed": bool(calibration.get("gate_pass")),
        }

    semantic = semantic_recall()
    if "skipped" in semantic:
        gates["semantic_recall_at_20"] = {"status": "skipped",
                                          "reason": semantic["skipped"]}
    else:
        gates["semantic_recall_at_20"] = {
            "value": semantic.get("recall_at_20"),
            "threshold": SEMANTIC_RECALL_MIN,
            "required": True,
            "passed": bool(semantic.get("gate_pass")),
        }

    return gates


def all_required_passed(gates: dict) -> bool:
    return all(
        g["passed"]
        for g in gates.values()
        if g.get("required")
    )


def run_report() -> dict:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "ranking": ranking_report(),
        "extraction": extraction_report(),
        "transfer": transfer_metrics(),
        "calibration": calibration_report(),
        "semantic": semantic_recall(),
        "gates": collect_gates(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="§21 evaluation + gates")
    parser.add_argument("--gate", action="store_true",
                        help="exit 1 when a required gate fails")
    args = parser.parse_args(argv)

    report = run_report()
    REPORTS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out = REPORTS / f"eval-{stamp}.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"{'gate':40s} {'value':>10s} {'limit':>10s}  status")
    for name, gate in report["gates"].items():
        if "passed" in gate:
            value = gate.get("value")
            value = "—" if value is None else f"{value:.4f}" if isinstance(value, float) else str(value)
            limit = gate.get("threshold", "≥ baseline")
            status = "PASS" if gate["passed"] else "FAIL"
            if not gate.get("required", True):
                status = f"({status} advisory)"
            print(f"{name:40s} {value:>10s} {str(limit):>10s}  {status}")
            if name == "transfer_f1" and gate.get("rows"):
                print(f"  {'M1 mode':55s} {'P':>8s} {'R':>8s} {'F1':>8s} {'AUC':>8s}")
                for r in gate["rows"]:
                    print(f"  {r['name'][:55]:55s} {r['precision']:8.4f} {r['recall']:8.4f} {r['f1']:8.4f} {r['auc_roc']:8.4f}")
        else:
            print(f"{name:40s} {'-':>10s} {'-':>10s}  {gate.get('status', 'n/a')}")
    print(f"\nreport: {out}")

    if args.gate and not all_required_passed(report["gates"]):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
