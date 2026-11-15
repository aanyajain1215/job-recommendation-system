"""§21 evaluation metrics — pure functions, exact, dependency-free.

Used by ml/evaluate.py, the ml train gates, and CI (test_eval_regression).
Conventions: every *_at_k function takes labels ALREADY ORDERED BY RANK;
`threshold` defines a "relevant" label (default ≥1 for graded labels).
"""

from __future__ import annotations

import math
from typing import Sequence


def precision_at_k(labels: Sequence[float], k: int, threshold: float = 1.0) -> float:
    if k <= 0:
        return 0.0
    top = list(labels)[:k]
    return sum(1 for x in top if x >= threshold) / k


def recall_at_k(labels: Sequence[float], k: int, threshold: float = 1.0) -> float:
    total = sum(1 for x in labels if x >= threshold)
    if total == 0:
        return 0.0
    top = list(labels)[:k]
    return sum(1 for x in top if x >= threshold) / total


def dcg_at_k(labels: Sequence[float], k: int) -> float:
    return sum((2.0**float(x) - 1.0) / math.log2(i + 2) for i, x in enumerate(list(labels)[:k]))


def ndcg_at_k(labels: Sequence[float], k: int) -> float:
    """NDCG@k for a ranked label list (ideal order = descending labels)."""
    if k <= 0:
        return 0.0
    ideal = sorted((float(x) for x in labels), reverse=True)
    idcg = dcg_at_k(ideal, k)
    if idcg <= 0:
        return 0.0
    return dcg_at_k([float(x) for x in labels], k) / idcg


def mrr_at_k(labels: Sequence[float], k: int, threshold: float = 1.0) -> float:
    for i, x in enumerate(list(labels)[:k]):
        if x >= threshold:
            return 1.0 / (i + 1)
    return 0.0


def brier_score(probs: Sequence[float], outcomes: Sequence[int]) -> float:
    """Mean squared error of probability vs 0/1 outcome (plan §21)."""
    n = len(probs)
    if n == 0:
        return 0.0
    return sum((float(p) - float(y)) ** 2 for p, y in zip(probs, outcomes)) / n


def expected_calibration_error(
    probs: Sequence[float], outcomes: Sequence[int], n_bins: int = 10
) -> float:
    """ECE over equal-width confidence bins (plan §21 gate ≤ 0.10)."""
    n = len(probs)
    if n == 0:
        return 0.0
    members: list[list[tuple[float, int]]] = [[] for _ in range(n_bins)]
    for p, y in zip(probs, outcomes):
        idx = min(n_bins - 1, max(0, int(float(p) * n_bins)))
        members[idx].append((float(p), int(y)))
    ece = 0.0
    for bucket in members:
        if not bucket:
            continue
        conf = sum(p for p, _ in bucket) / len(bucket)
        acc = sum(y for _, y in bucket) / len(bucket)
        ece += (len(bucket) / n) * abs(acc - conf)
    return ece


def precision_recall_f1(
    y_true: Sequence[bool], y_pred: Sequence[bool]
) -> tuple[float, float, float]:
    tp = sum(1 for t, p in zip(y_true, y_pred) if t and p)
    fp = sum(1 for t, p in zip(y_true, y_pred) if not t and p)
    fn = sum(1 for t, p in zip(y_true, y_pred) if t and not p)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return precision, recall, f1


def set_f1(expected: set[str], predicted: set[str]) -> float:
    """Set-level F1 for one item (skill extraction, plan §21)."""
    if not expected and not predicted:
        return 1.0
    tp = len(expected & predicted)
    precision = tp / len(predicted) if predicted else 0.0
    recall = tp / len(expected) if expected else 0.0
    return (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0


def micro_f1(pairs: Sequence[tuple[set, set]]) -> float:
    """Micro-averaged F1 over many (expected, predicted) set pairs."""
    tp = fp = fn = 0
    for expected, predicted in pairs:
        tp += len(expected & predicted)
        fp += len(predicted - expected)
        fn += len(expected - predicted)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    return (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0


def recall_at_k_over_corpus(
    query_vecs: Sequence[list[float]],
    doc_vecs: Sequence[list[float]],
    relevant: Sequence[set[int]],
    k: int = 20,
) -> float:
    """Mean Recall@k of cosine retrieval over a frozen corpus (plan §21)."""
    if not query_vecs:
        return 0.0
    scores: list[float] = []
    for q, rel in zip(query_vecs, relevant):
        if not rel:
            continue
        sims = [_cosine(q, d) for d in doc_vecs]
        order = sorted(range(len(sims)), key=lambda i: -sims[i])
        top = order[:k]
        scores.append(len(rel & set(top)) / len(rel))
    return sum(scores) / len(scores) if scores else 0.0


def average_precision_at_k(labels: Sequence[float], k: int, threshold: float = 1.0) -> float:
    """AP@k for a ranked label list (binary relevance by threshold)."""
    if k <= 0:
        return 0.0
    top = list(labels)[:k]
    total_rel = sum(1 for x in labels if x >= threshold)
    if total_rel == 0:
        return 0.0
    hits = 0
    score = 0.0
    for i, x in enumerate(top, start=1):
        if x >= threshold:
            hits += 1
            score += hits / i
    return score / min(total_rel, k)


def map_at_k(labels: Sequence[float], k: int, threshold: float = 1.0) -> float:
    """Alias-style single-list MAP@k (same as AP@k for one ranked list)."""
    return average_precision_at_k(labels, k, threshold=threshold)


def auc_roc_binary(y_true: Sequence[int], scores: Sequence[float]) -> float:
    """AUC-ROC via rank statistic (handles ties by average rank)."""
    n = len(y_true)
    if n == 0:
        return 0.0
    pos = sum(1 for y in y_true if int(y) == 1)
    neg = n - pos
    if pos == 0 or neg == 0:
        return 0.0
    order = sorted(range(n), key=lambda i: float(scores[i]))
    ranks = [0.0] * n
    i = 0
    r = 1
    while i < n:
        j = i
        while j + 1 < n and float(scores[order[j + 1]]) == float(scores[order[i]]):
            j += 1
        avg_rank = (r + (r + (j - i))) / 2.0
        for kidx in range(i, j + 1):
            ranks[order[kidx]] = avg_rank
        r += (j - i + 1)
        i = j + 1
    sum_pos_ranks = sum(rank for rank, y in zip(ranks, y_true) if int(y) == 1)
    auc = (sum_pos_ranks - pos * (pos + 1) / 2.0) / (pos * neg)
    return float(max(0.0, min(1.0, auc)))


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na <= 0 or nb <= 0:
        return 0.0
    return dot / (na * nb)
