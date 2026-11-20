# JobRec — Project State (Current Snapshot)

> Snapshot date: **2026-04-16** (repository state); ML section 2a updated **2026-11-20**. This document summarizes the current implementation, workflow, and operational notes. For historical design intent, see [`DESIGN.md`](DESIGN.md).

## 1. Current implementation summary

### Stack
- **Frontend:** Next.js 16 (App Router), React 19, Tailwind CSS 4, TanStack Query
- **Backend:** FastAPI, SQLAlchemy 2.x, Alembic, Pydantic v2
- **Database:** PostgreSQL + pgvector
- **ML/AI:** PyTorch-based retrieval/ranking components, calibration, bandit evaluation, and agentic roadmap planning (M0–M5 pipeline)

### Core workflow
1. **User/profile & auth:** JWT-based auth with role-based flows (job seeker/employer/admin).
2. **Job sourcing:**
   - **Live Adzuna jobs** are fetched at query time and merged into search/recommendation responses (transient `adzuna-*` listings, external apply URL).
   - **Native jobs** can exist as platform postings (DB-backed flows).
3. **Recommendation/search:** candidate retrieval + learned ranking + calibrated scoring + explanation/trace outputs (implementation varies by path/config).
4. **Career tools:** skill gap, roadmap, simulator, resume/profile features.
5. **Saved jobs UX:** native saves via backend; external Adzuna listings can be saved locally in-browser for the Saved Jobs view.

## 2. M0–M5 pipeline (current)

| Stage | Current implementation | Evaluation/artifacts |
|---|---|---|
| **M0 Retrieval** | Domain-tuned `BAAI/bge-base-en-v1.5` bi-encoder (768-d) + cross-encoder reranker (two-stage retrieval) | `backend/ml/reports/m0_embedding_eval.json`, fine-tuned model artifacts in `backend/ml/artifacts/` (large weights may be local-only) |
| **M1 Skill graph** | Relational GraphSAGE over directed Skill–Role–Project graph (inductive, contrastive link prediction; hybrid graph+embedding transfer usage) | Training/eval via ML scripts and unified evaluator |
| **M2 Ranking** | PyTorch DCN-v2 neural ranker (31-feature schema), profile-split eval with heuristic/LightGBM baselines | Ranker artifacts/metrics in `backend/ml/artifacts/` and `backend/ml/reports/` |
| **M3 Calibration** | Calibrator trained on DCN-v2 logits (`input_kind=dcn_logit`) with stratified OOF pre/post ECE/Brier metrics; production fit on validation logits | Calibrator artifacts and calibration outputs in `backend/ml/artifacts/` |
| **M4 Bandit/personalization** | NeuralUCB contextual bandit with OPE evaluation (IPS/SNIPS/cumulative regret) | `backend/ml/eval_bandit.py`, `backend/ml/artifacts/bandit_ope_report.json`, regret/metrics artifacts |
| **M5 Planning** | 3-stage Agentic Planner–Critic roadmap generation with `agent_trace` (gap/prereq analysis, curriculum/project planning, feasibility/grounding critic) | Evaluated on real DB `(profile, job)` pairs in unified evaluation |

### Unified evaluation
- **Command:** `python backend/ml/evaluate_all.py` (run from `backend/` with required env/DB/deps)
- **Master report:** `backend/ml/reports/master_project_evaluation.json`
- Prints aggregated M0–M5 summaries and writes JSON output

## 2a. ML on real data (Nov 2026 overhaul) — what changed and why

### Why the previous ML was not credible
| Problem | Effect |
|---|---|
| Ranker labels came from `ml/ground_truth.py`: the hand-written `scoring.py` score + noise | The DCN learned to copy the formula (formula NDCG 0.959 vs DCN 0.961) |
| Ranker judged on 6 test queries; bi-encoder "fine-tuned" on 37 positive pairs | Numbers too small to mean anything |
| GNN trained on ~100 hand-written YAML lines and tested on pairs generated from the same clusters | Circular; AUC 0.96 measured memorisation |
| `build_datasets.py` read cross-encoder output in the wrong format and swallowed the error | Cross-encoder features were always 0 in ranker training |
| Fine-tuned weights missing, config paths empty | The app silently used the off-the-shelf models |
| Ranker trainer picked its best epoch on the test set | Inflated reported scores |
| Displayed score was `max(calibrated, raw)` | Calibration was overridden |

### What replaced it (all evaluated on held-out data, always against baselines)
| Model | Data | Script | Held-out evaluation |
|---|---|---|---|
| Cross-encoder (M0) | Resume–JD Fit (HuggingFace, human labels) | `ml/train_cross_encoder_real.py` | Official test split; all 71 test jobs unseen |
| Skill graph (M1) | O*NET 31.0 occupation→technology | `ml/onet.py`, `ml/train_skill_graph_onet.py` | 20% of links hidden; hard negatives from the same job group |
| Ranker (M2) | CareerBuilder 2012 real applications, tech jobs | `ml/build_careerbuilder_dataset.py` → `ml/train_neural_ranker.py --data-dir ml/datasets/careerbuilder` | Time split: weeks 1–5 train, 6 val (epoch/early stopping), 7 test; no user overlap |
| Calibrator (M3) | CareerBuilder validation week | `ml/calibrate.py --data-dir ml/datasets/careerbuilder` | Fit on val, reported on test |

Every ranker feature is computed with the app's own serving code (skill extractor, embedder, cross-encoder, skill graph, `score_pair`, `build_features`), so train == serve.

### Leaks found and fixed while building the ranker dataset
A first run scored NDCG 0.97 with 99% of LightGBM's gain on `job_age_days`. Causes, all fixed: (1) negatives' reference date stored in a format the parser rejected, so every negative had age 0; (2) 7.5k negatives were posted after the user's search time; (3) rows were written positives-first, so tied scores were broken in the model's favour (now hashed order + seeded random tie-break in the evaluator). After fixes the strongest single feature has AUC 0.71 (text similarity).

### Other fixes
- Location matching (`app/services/location.py`): "Pune, India" == "Pune, Maharashtra", Bangalore == Bengaluru, city→state for major Indian cities.
- Calibrated score shown as-is; ties broken by the DCN logit; readiness no longer calibrated twice.
- Newest model files chosen by numeric version (v10 > v9) for skill vectors, ranker, calibrator.
- Bandit: simulation-trained policies moved to `ml/artifacts/simulation/`; the live policy starts fresh and learns online (`ml/artifacts/bandit_online.joblib`, git-ignored).

### Known limitations (state these in reports)
- CareerBuilder is 2012, US, and mostly non-tech; only its tech subset is used. The ranker learns how much each signal matters (similarity, location, freshness, skill fit), not job-title vocabulary.
- CareerBuilder users have no skills list (skills come from past job titles); no salary or education signals.
- The bi-encoder is not fine-tuned (off-the-shelf BGE).
- 25 app skills (e.g. "machine learning", FastAPI) have no O*NET equivalent and get no skill vector; the app falls back to curated edges.
- LightGBM beats the served DCN (NDCG 0.802 vs 0.762); the app currently serves only DCN.
- Roadmap/simulator/gap readiness still pass the formula score through the DCN-logit calibrator (pre-existing; semantically loose).
- Best future data: the app's own logged interactions (`ml/build_datasets.py`), once real users exist.

### Reproduce (CPU; training env in `backend/.venv`, see `backend/ml/requirements-train.txt`)
```
python ml/train_cross_encoder_real.py
python ml/train_skill_graph_onet.py
python ml/build_careerbuilder_dataset.py      # needs the Kaggle files in ml/data/external/careerbuilder/
python ml/train_neural_ranker.py --data-dir ml/datasets/careerbuilder --version v2
python ml/calibrate.py --data-dir ml/datasets/careerbuilder --no-register
python ml/evaluate_all.py
```

## 3. Frontend/UI state (current)

- **Theme:** yellow + blue, high-visibility light palette with larger/bolder typography
- **Auth/onboarding:** signup questionnaire removed; registration routes to dashboard and `/onboarding` redirects to dashboard
- **Navigation:** **Tracker** and **Settings** tabs/pages removed
- **Jobs UX:** live Adzuna jobs open in an **in-app job detail modal** (with external apply link) instead of direct redirect; native jobs retain in-app/detail flows
- **Saved jobs:** supports saved external Adzuna listings in browser-local storage and displays them in Saved Jobs
- **Salary formatting:** currency/location-aware (e.g. INR/₹ formatting for Indian listings, appropriate symbols for other currencies)

## 4. Database & migrations

- Alembic migration chain is present under `backend/alembic/versions/`
- Current head in this repo includes: `0013_m0_bge768_embeddings`, `0013_phase1_integrity`, `0014_phase2_traceability` (upgrade with `alembic upgrade head`)
- Backend Docker startup applies migrations automatically
- Live Adzuna results are query-time/transient (not persisted as native job rows)

## 5. How to run

### Docker (recommended)
```powershell
# first time / after rebuild needs
copy .env.example .env
docker compose up --build

# subsequent runs
docker compose up -d
```

- Frontend: `http://localhost:3000`
- Backend: `http://localhost:8000` (`/docs`, `/api/v1/health`)
- Postgres host port: `localhost:55432`

### Local (without Docker)
- Backend: install `backend/requirements.txt`, run `alembic upgrade head`, start `uvicorn app.main:app --reload`
- Frontend: `npm ci`, `npm run dev` in `frontend/`
- Configure `.env` / API URLs appropriately

## 6. Known caveats / operational notes

- **Live jobs depend on Adzuna credentials/config** (`ADZUNA_APP_ID`, `ADZUNA_APP_KEY`, `ADZUNA_COUNTRY`) for external results.
- **External saved jobs** (Adzuna) are stored in browser local storage (not server-side DB records).
- **Large fine-tuned model weights** (e.g. `.safetensors` for bi-encoder/cross-encoder) may be kept local/untracked due to size; regenerate via ML training scripts as needed.
- **Evaluation/runtime variability:** some features/tests depend on DB state, model artifacts, environment flags, and optional LLM/provider availability.
- **M4/M5 results:** performance characteristics and coverage depend on current data/artifacts/benchmark setup; refer to `backend/ml/reports/master_project_evaluation.json` and related artifacts for the latest measured outputs.
- **Browser caching:** after frontend changes, use hard refresh/incognito if stale UI appears.

## 7. Key paths

- `README.md` — setup and usage
- `frontend/` — UI application
- `backend/app/` — API, services, models
- `backend/ml/` — training, evaluation, artifacts, reports
- `backend/alembic/versions/` — migrations
- `docker-compose.yml` — local orchestration
