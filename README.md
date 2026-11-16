# JobRec — AI/ML Job Recommendation System

JobRec is a full-stack job recommendation and career-path platform built with **Next.js (App Router)**, **FastAPI**, and **PostgreSQL + pgvector**. It combines retrieval, graph reasoning, neural ranking, calibration, contextual bandits, and LLM-assisted planning to deliver job matches, skill-gap insights, and roadmaps.

> **Note:** This README reflects the current implementation/workflow in this repository. For historical design intent, see [`docs/DESIGN.md`](docs/DESIGN.md).

## Current system at a glance

### Core capabilities
- **Job discovery & recommendations:** candidate generation + learned ranking + calibrated match scores
- **Live jobs:** query-time **Adzuna** results are fetched and merged into search/recommendation flows (transient `adzuna-*` listings, external apply). Native employer-posted jobs are supported in-app.
- **Career intelligence:** skill-gap analysis, roadmap generation, simulator, resume optimization, and profile-driven personalization
- **Auth/roles:** job seeker, employer, admin flows
- **Frontend UX (current):** yellow/blue high-visibility theme, no signup questionnaire (register → dashboard), no Tracker/Settings tabs, in-app job detail modal for live listings, local save support for external (Adzuna) jobs, currency-aware salary display (₹ for Indian listings, appropriate symbols by currency/location)

### ML/AI pipeline (M0–M5, current)
| Stage | Current implementation | Notes / artifacts |
|---|---|---|
| **M0 Retrieval** | Domain-tuned **`BAAI/bge-base-en-v1.5` bi-encoder (768-d)** + **cross-encoder reranker** (two-stage retrieval) | M0 eval/report artifacts under `backend/ml/reports/` (e.g. `m0_embedding_eval.json`) and fine-tuned model dirs under `backend/ml/artifacts/` |
| **M1 Skill/graph reasoning** | **Relational GraphSAGE** over directed Skill–Role–Project graph (inductive, contrastive link prediction) | Trained/evaluated via ML scripts; hybrid graph+embedding transfer logic used in runtime paths |
| **M2 Ranking** | **PyTorch DCN-v2** neural ranker (31-feature schema, profile-split training/eval) with LightGBM/heuristic baselines for comparison | Primary learned ranking path (AI-strict/learned-primary runtime strategy) |
| **M3 Calibration** | **Calibrator on DCN-v2 logits** (`input_kind=dcn_logit`) with stratified OOF pre/post metrics; production fit on val logits | Produces calibrated readiness/match probabilities/scores for display and downstream use |
| **M4 Personalization/bandit** | **NeuralUCB** contextual bandit (with compatibility for prior policy interfaces), evaluated via IPS/SNIPS/regret (OPE) | Artifacts/reports under `backend/ml/artifacts/` and `backend/ml/reports/` |
| **M5 Planning** | **3-stage Agentic Planner–Critic** roadmap pipeline with `agent_trace` (gap/prereq analysis → curriculum/project planning → feasibility/grounding critic) | Evaluated on real DB `(profile, job)` pairs in unified evaluation |

**Unified evaluation:** `backend/ml/evaluate_all.py` aggregates M0–M5 into `backend/ml/reports/master_project_evaluation.json` and prints summary tables.

## Tech stack

- **Frontend:** Next.js 16 (App Router), React 19, Tailwind CSS 4, TanStack Query
- **Backend:** FastAPI, SQLAlchemy, Alembic, Pydantic v2
- **Database:** PostgreSQL + **pgvector**
- **ML:** PyTorch, sentence-transformers/cross-encoders, scikit-learn, LightGBM, NumPy, etc. (see `backend/requirements.txt`)
- **LLM layer:** provider-backed LLM features with validation/fallback behavior (configured via `.env`; optional depending on feature/flags)

## Repository layout

- `frontend/` — Next.js app (pages, components, API client, styling)
- `backend/` — FastAPI app, services, models, migrations, ML training/evaluation
  - `backend/app/api/` — API routers
  - `backend/app/services/` — recommendation, retrieval/rerank, roadmap, live jobs, etc.
  - `backend/ml/` — training/evaluation scripts, datasets, artifacts, reports
  - `backend/alembic/versions/` — DB migrations
- `docs/` — design and project state documentation
- `docker-compose.yml` — local stack (Postgres, backend, frontend)

## Prerequisites

- **Docker Desktop** with **Docker Compose v2** (recommended)
- Optional: **Adzuna API credentials** for live job fetch (`ADZUNA_APP_ID`, `ADZUNA_APP_KEY`, `ADZUNA_COUNTRY`)
- Optional: LLM provider credentials/flags for LLM-dependent features

## Run with Docker (recommended)

### 1) Configure environment
From the project root:

```powershell
Copy-Item .env.example .env
```

Update `.env` as needed:
- **Ports/URLs:** `FRONTEND_PORT`, `API_PORT`, `POSTGRES_PORT`, `NEXT_PUBLIC_API_URL`
- **Database:** `POSTGRES_*`, `DATABASE_URL`
- **Live jobs (Adzuna):** `ADZUNA_APP_ID`, `ADZUNA_APP_KEY`, `ADZUNA_COUNTRY` (e.g. `in`)
- **LLM (optional):** provider/model/key flags as configured in your environment

### 2) Start the stack

```powershell
docker compose up --build
```

- Backend container runs migrations on startup (`alembic upgrade head`)
- Source volumes are mounted for local development; behavior may depend on container command/hot-reload setup

**After first build (normal restart):**

```powershell
docker compose up -d
```

### 3) Access the app
- **Frontend:** http://localhost:3000
- **Backend API:** http://localhost:8000
- **Swagger docs:** http://localhost:8000/docs
- **Health:** http://localhost:8000/api/v1/health
- **Readiness:** http://localhost:8000/api/v1/health/ready
- **Postgres (host):** `localhost:55432` (container listens on `5432` internally)

### 4) Demo credentials (if present in DB)
- **Job seeker:** `aanya.seeker@example.com` / `Password123!`
- **Employer:** `employer.qa@jobrec.io` / `Password123!`
- **Admin:** `admin.qa@jobrec.io` / `Password123!`

## Common Docker commands

```powershell
# Start detached
docker compose up -d

# Rebuild images (after dependency/Dockerfile changes)
docker compose up --build -d

# Status / logs
docker compose ps
docker compose logs -f backend
docker compose logs -f frontend

# Restart a service
docker compose restart frontend

# Stop / remove containers
docker compose stop
docker compose down
```

> Use `docker compose up --build` when dependencies or Docker build inputs change. For routine restarts, `docker compose up -d` (or `docker compose start` for stopped containers) is sufficient.

## Workflow notes

- **Live Adzuna jobs:** fetched at query time and processed through search/recommendation pipelines. Listings are transient (`adzuna-*`), open externally for apply, and are not stored as native DB job rows.
- **Saving jobs:** native jobs use backend persistence; live external Adzuna listings are saved locally in the browser (Saved Jobs view) because they are not DB records.
- **Currency display:** salary formatting is location/currency-aware (e.g. Indian listings show **₹/L/Cr** where applicable).
- **Frontend caching:** after UI/theme changes, do a hard refresh (`Ctrl+Shift+R`) or use incognito if you see stale styling/routes.

## Local development (without Docker)

Requires **Python 3.13+**, **Node.js 22+**, and **PostgreSQL (pgvector-enabled)**.

1. Create/configure `.env` and ensure `DATABASE_URL` points to your local Postgres.
2. **Backend** (`backend/`):
   ```powershell
   pip install -r requirements.txt
   alembic upgrade head
   uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
   ```
3. **Frontend** (`frontend/`):
   ```powershell
   npm ci
   npm run dev
   ```
4. Ensure frontend API env vars point to the backend (e.g. `NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1`).

## Evaluation & model workflows

Run from `backend/` (with required environment, DB access, and dependencies configured):

```powershell
# Unified M0–M5 evaluation (writes master report)
python ml/evaluate_all.py

# Bandit/OPE evaluation (as used by project scripts)
python ml/eval_bandit.py
```

- **Master report:** `backend/ml/reports/master_project_evaluation.json`
- **Model artifacts:** `backend/ml/artifacts/`
- **Datasets/reports:** `backend/ml/datasets/`, `backend/ml/reports/`

> Some fine-tuned model weight files (e.g. large `.safetensors`) may be kept local/untracked due to size. Regeneration/training scripts (e.g. bi-encoder/cross-encoder trainers) are available in `backend/ml/` when the full training environment is set up.

## Testing

```powershell
# Backend (example; configure DB/env for your setup)
cd backend
python -m pytest tests -q

# Frontend
cd frontend
npx tsc --noEmit
npm run build
```

> Test/runtime behavior may depend on external services, DB state, model artifacts, and strict/LLM configuration flags.

## Database migrations

- Alembic versions: `backend/alembic/versions/`
- Current migration chain in this repo includes M0/traceability revisions through **`0014_phase2_traceability`**
- Docker startup applies migrations automatically; for local runs use `alembic upgrade head`

## Additional docs

- [`docs/DESIGN.md`](docs/DESIGN.md) — original/expanded technical design (historical reference)
- [`docs/PROJECT_STATE.md`](docs/PROJECT_STATE.md) — project state snapshot and operational notes
- ML reports under `backend/ml/reports/` — latest evaluation outputs (when generated)
