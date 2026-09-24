"""§21 evaluation gates + metric exactness (plan §21).

Golden data, datasets, and trained artifacts are committed, so these gates
run offline.  Cases that need an unavailable dependency (ranklet not yet
trained in a fresh clone, embedder failure) skip with an explicit reason
instead of passing vacuously — `python ml/train.py` produces everything.
"""

import json
import math
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend/
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://x:x@localhost:55432/x")
os.environ.setdefault("EMBEDDING_BACKEND", "minilm")

BACKEND = Path(__file__).resolve().parents[1]
GOLDEN = BACKEND / "ml" / "data" / "golden"
DATASETS = BACKEND / "ml" / "datasets"
ARTIFACTS = BACKEND / "ml" / "artifacts"


def _jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


# ---------------------------------------------------------------------------
# Metric exactness (hand-computed)
# ---------------------------------------------------------------------------

def test_ndcg_at_k_exact():
    from ml.metrics import ndcg_at_k

    labels = [3, 2, 0, 2]
    dcg = 7 / 1 + 3 / math.log2(3) + 0 + 3 / math.log2(5)
    idcg = 7 / 1 + 3 / math.log2(3) + 3 / math.log2(4) + 0
    assert ndcg_at_k(labels, 4) == pytest.approx(dcg / idcg, rel=1e-9)
    assert ndcg_at_k([3, 2, 1], 3) == pytest.approx(1.0)   # perfect ordering
    assert ndcg_at_k([0, 0, 0], 3) == 0.0                   # nothing relevant
    assert ndcg_at_k([2, 0, 0], 1) == pytest.approx(1.0)    # top-1 hit
    # single relevant item ranked last — strictly between 0 and 1
    assert 0.0 < ndcg_at_k([0, 2], 2) < 1.0


def test_precision_recall_mrr_exact():
    from ml.metrics import mrr_at_k, precision_at_k, recall_at_k

    labels = [2, 0, 2, 0]
    assert precision_at_k(labels, 2) == pytest.approx(0.5)
    assert recall_at_k(labels, 2) == pytest.approx(0.5)
    assert mrr_at_k(labels, 4) == pytest.approx(1.0)
    assert mrr_at_k([0, 0, 2], 3) == pytest.approx(1 / 3)
    assert mrr_at_k([0, 0, 0], 3) == 0.0
    assert precision_at_k([0, 0], 2) == 0.0
    # k beyond the list retrieves every relevant item; partial case: 1 of 3
    assert recall_at_k([1, 1, 1], 10) == 1.0
    assert recall_at_k([1, 0, 1, 0, 1], 2) == pytest.approx(1 / 3)


def test_brier_ece_f1_exact():
    from ml.metrics import (
        brier_score,
        expected_calibration_error,
        micro_f1,
        precision_recall_f1,
    )

    probs = [0.9, 0.8, 0.3, 0.4]
    outcomes = [1, 1, 0, 0]
    assert brier_score(probs, outcomes) == pytest.approx(0.075)
    # 10-bin ECE: bin9 |1-0.9|×1/4 + bin8 |1-0.8|×1/4 + bin3 0.3×1/4 +
    # bin4 0.4×1/4 = (0.1 + 0.2 + 0.3 + 0.4)/4 = 0.25
    assert expected_calibration_error(probs, outcomes) == pytest.approx(0.25)

    p, r, f1 = precision_recall_f1(
        [True, True, False, False], [True, True, True, False]
    )
    assert p == pytest.approx(2 / 3)
    assert r == pytest.approx(1.0)
    assert f1 == pytest.approx(0.8)

    assert micro_f1([({"a", "b", "c"}, {"a", "b"})]) == pytest.approx(0.8)


# ---------------------------------------------------------------------------
# Golden data shape (plan §21 fixtures)
# ---------------------------------------------------------------------------

def test_golden_corpus_shape():
    postings = _jsonl(GOLDEN / "postings.jsonl")
    resumes = _jsonl(GOLDEN / "resumes.jsonl")
    transfers = _jsonl(GOLDEN / "transfer_pairs.jsonl")
    relevance = _jsonl(GOLDEN / "relevance_pairs.jsonl")

    assert len(postings) == 100
    assert len(resumes) == 50
    positives = [p for p in transfers if p["transferable"]]
    negatives = [p for p in transfers if not p["transferable"]]
    assert len(positives) >= 100, "plan §21: ≥100 transferable pairs"
    assert len(negatives) >= 100, "plan §21: ≥100 non-transferable pairs"
    assert len(relevance) >= 18, "plan §21: labeled semantic queries"
    # every resume has exact expected skills
    assert all(r["expected"]["skills"] for r in resumes)


# ---------------------------------------------------------------------------
# §21 gates
# ---------------------------------------------------------------------------

def test_extraction_f1_gate():
    from ml.evaluate import extraction_report

    report = extraction_report()
    assert "skipped" not in report, report
    assert report["f1"] >= 0.85, (
        f"skill extraction F1 {report['f1']} < 0.85 gate: {report}"
    )


def test_transfer_f1_gate():
    from ml.evaluate import transfer_metrics

    report = transfer_metrics()
    assert "skipped" not in report, report
    assert report["vectors"] is True, (
        "skill2vec artifact must be committed (python ml/train_skill2vec.py)"
    )
    assert report["f1"] >= 0.80, (
        f"transfer F1 {report['f1']} < 0.80 gate: {report}"
    )


def test_semantic_recall_gate():
    from ml.evaluate import semantic_recall

    report = semantic_recall(20)
    if "skipped" in report:
        pytest.skip(report["skipped"])
    assert report["recall_at_20"] >= 0.75, (
        f"Recall@20 {report['recall_at_20']} < 0.75 gate: {report}"
    )


def test_ranklet_beats_deterministic_gate():
    if not sorted(ARTIFACTS.glob("ranklet_v*.txt")):
        pytest.skip("ranklet not trained yet — run: python ml/train.py")
    from ml.evaluate import ranking_report

    report = ranking_report()
    assert report is not None, "datasets missing — run python ml/train.py"
    assert report["ranklet_trained"] is True
    ranklet = report["metrics"]["ranklet"]["ndcg_at_10"]
    deterministic = report["metrics"]["deterministic"]["ndcg_at_10"]
    assert ranklet >= deterministic, (
        f"ranklet NDCG@10 {ranklet} < deterministic {deterministic}"
    )


def test_calibration_ece_gate():
    if not sorted(ARTIFACTS.glob("calibrator_v*.joblib")):
        pytest.skip("calibrator not trained yet — run: python ml/train.py")
    from ml.evaluate import calibration_report

    report = calibration_report()
    assert report is not None
    assert report["ece"] <= 0.10, f"ECE {report['ece']} > 0.10 gate: {report}"


def test_model_registry_has_trained_models():
    """Plan §17: the model registry contains M1–M3 rows with metrics."""
    import ml.ml_registry as registry

    expectations = [
        ("skill2vec", "skill2vec_v*.joblib"),
        ("ranklet", "ranklet_v*.txt"),
        ("isotonic-calibrator", "calibrator_v*.joblib"),
    ]
    missing_artifacts = [
        name for name, pattern in expectations
        if not sorted(ARTIFACTS.glob(pattern))
    ]
    if missing_artifacts:
        pytest.skip(f"artifacts missing ({missing_artifacts}) — run: python ml/train.py")

    for name, _pattern in expectations:
        row = registry.get_row(name)
        assert row is not None, (
            f"{name} missing from model_registry — run: python ml/train.py"
        )
        assert row["metrics"], f"{name} registry row has empty metrics"
        assert row["artifact_path"]

    from app.core.config import get_settings

    settings = get_settings()
    assert settings.recommender_strategy in ("deterministic", "ltr_blend", "ltr_full")
    assert settings.readiness_calibrator_enabled is True
    assert settings.readiness_band_high > settings.readiness_band_medium


def test_ranklet_manifest_feature_order_matches_serving():
    if not sorted(ARTIFACTS.glob("ranklet_v*.manifest.json")):
        pytest.skip("ranklet manifest missing — run: python ml/train.py")
    from app.services.rerank import FEATURE_ORDER

    manifest = json.loads(
        sorted(ARTIFACTS.glob("ranklet_v*.manifest.json"))[-1].read_text(
            encoding="utf-8"
        )
    )
    assert manifest["feature_order"] == FEATURE_ORDER
    assert "metrics" in manifest


# ---------------------------------------------------------------------------
# Feature vector contract + honest-degradation guards
# ---------------------------------------------------------------------------

def test_feature_vector_deterministic_and_manifest_sized():
    from app.models.enums import ExperienceLevel, ProficiencyLevel
    from app.services.rerank import (
        FEATURE_ORDER,
        FeatureContext,
        build_features,
        component_vector,
    )
    from app.services.scoring import JobSkillReq, score_pair

    from app.services.scoring import ComponentInputs  # noqa: PLC0415

    inputs = ComponentInputs(
        seeker_skills={"python": (ProficiencyLevel.ADVANCED, 3.0)},
        job_skills=[
            JobSkillReq(name="python", is_required=True),
            JobSkillReq(name="kubernetes", is_required=True),
        ],
        semantic_cosine=0.77,
        years_of_experience=5.0,
        job_level=ExperienceLevel.MID,
    )
    result = score_pair(inputs)
    ctx = FeatureContext(job_age_days=3.5, applicant_count=2.0,
                         profile_completeness=80.0, historical_apply_rate=0.04)
    v1 = build_features(inputs, result, ctx)
    v2 = build_features(inputs, result, ctx)
    assert v1 == v2, "feature build must be deterministic"
    assert len(v1) == len(FEATURE_ORDER) == 30
    assert all(isinstance(x, (int, float)) and math.isfinite(x) for x in v1)
    assert len(component_vector(result)) == 30
    # required coverage: python held → 1.0; kubernetes missing → 0.0
    assert v1[FEATURE_ORDER.index("required_coverage")] == pytest.approx(0.5)
    assert v1[FEATURE_ORDER.index("semantic_cosine_raw")] == pytest.approx(0.77)


def test_ranklet_manifest_mismatch_degrades_honestly():
    """A manifest whose feature_order differs must block loading (→ deterministic)."""
    import app.services.rerank as rerank_mod

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        (tmp_path / "ranklet_v9.txt").write_text("dummy model", encoding="utf-8")
        (tmp_path / "ranklet_v9.manifest.json").write_text(
            json.dumps({"feature_order": ["wrong_feature"]}), encoding="utf-8"
        )
        original = rerank_mod.ARTIFACT_DIR
        rerank_mod.ARTIFACT_DIR = tmp_path
        rerank_mod.reset_cache()
        try:
            booster, version, order = rerank_mod._load_lgbm()
            assert booster is None and version is None and order is None
        finally:
            rerank_mod.ARTIFACT_DIR = original
            rerank_mod.reset_cache()


def test_ranklet_artifact_exists_and_loads_with_matching_manifest():
    candidates = sorted(ARTIFACTS.glob("ranklet_v*.txt"))
    if not candidates:
        pytest.skip("ranklet not trained yet — run: python ml/train.py")
    import app.services.rerank as rerank_mod

    rerank_mod.reset_cache()
    booster, version, order = rerank_mod._load_lgbm()
    assert booster is not None, "committed ranklet must load for serving"
    assert version is not None
    from app.services.rerank import FEATURE_ORDER  # noqa: PLC0415

    assert order == FEATURE_ORDER
