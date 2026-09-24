#!/usr/bin/env python
"""Model-suite orchestrator (plan §6/§17/§21): M1 → datasets → M2 → M3 →
evaluation → gated promotion.

    python ml/train.py            # full run (golden files auto-generated)
    python ml/train.py --skip-seed-hint

Sequence:
    1. ensure golden corpus exists (scripts/synthesize_corpus.py)
    2. M1  ml/train_skill2vec.py   (artifact + registry row, promoted)
    3.     ml/build_datasets.py     (needs scripts/seed_synthetic_users.py rows)
    4. M2  ml/train_ranklet.py      (artifact + manifest + registry row)
    5. M3  ml/calibrate.py          (artifact + registry row, promoted)
    6.     ml/evaluate.py --gate     (§21 baseline table)
    7. promote the ranklet only when its NDCG@10 ≥ deterministic baseline —
       otherwise serving keeps honestly reporting `deterministic`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def ensure_golden() -> None:
    golden = BACKEND_ROOT / "ml" / "data" / "golden"
    needed = ["postings.jsonl", "resumes.jsonl", "transfer_pairs.jsonl",
              "relevance_pairs.jsonl"]
    if all((golden / name).exists() for name in needed):
        return
    from scripts.synthesize_corpus import build_all  # noqa: PLC0415

    print("[train] generating golden corpus …")
    print(json.dumps(build_all(), indent=2))


def main() -> int:
    summary: dict[str, object] = {}

    ensure_golden()

    print("[train] M1 skill2vec …")
    from ml import train_skill2vec  # noqa: PLC0415

    summary["skill2vec"] = train_skill2vec.run(register=True)

    print("[train] datasets …")
    from ml import build_datasets  # noqa: PLC0415

    try:
        summary["datasets"] = build_datasets.run()
    except SystemExit as exc:
        if exc.code == 3:
            print(
                "[train] no interaction rows — run:\n"
                "        python scripts/seed_synthetic_users.py",
                file=sys.stderr,
            )
        raise

    print("[train] M2 ranklet …")
    from ml import train_ranklet  # noqa: PLC0415

    ranklet_result = train_ranklet.run(register=True)
    summary["ranklet"] = {
        "version": ranklet_result["version"],
        "gate_pass": ranklet_result["gate_pass"],
        "metrics": ranklet_result["metrics"],
    }

    print("[train] M3 calibrator …")
    from ml import calibrate  # noqa: PLC0415

    summary["calibrator"] = calibrate.run(register=True)

    print("[train] evaluation (§21) …")
    import ml.evaluate as evaluate  # noqa: PLC0415
    import ml.ml_registry as registry  # noqa: PLC0415

    report = evaluate.run_report()
    summary["gates"] = report["gates"]

    # gated promotion of the ranklet
    gate = report["gates"].get("ranking_ndcg_vs_deterministic", {})
    if gate.get("passed"):
        registry.promote("ranklet", ranklet_result["version"])
        summary["ranklet_promoted"] = True
    else:
        summary["ranklet_promoted"] = False
        print(
            "[train] ranklet gate did not pass — artifact kept for analysis, "
            "serving strategy stays deterministic",
            file=sys.stderr,
        )

    summary["all_required_gates_passed"] = evaluate.all_required_passed(
        report["gates"]
    )
    print(json.dumps(summary, indent=2, default=str))
    return 0 if summary["all_required_gates_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
