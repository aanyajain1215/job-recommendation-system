# JobRec — Project State (Current Snapshot)

> Snapshot date: **2026-04-16** (repository state). This document summarizes the current implementation, workflow, and operational notes. For historical design intent, see [`DESIGN.md`](DESIGN.md).

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
