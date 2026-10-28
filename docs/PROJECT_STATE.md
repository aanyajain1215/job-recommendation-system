# JobRec — Complete Project State, Architecture & Inventory

> One-file reference. Snapshot date: **2026-09-26**, commit `6afd53f`, branch `main` (19 commits, **all unpushed**).
> Everything below was re-verified against the running stack, not from memory.

---

## 1. Current State of the Project

### 1.1 What is running

```
NAMES             STATUS
jobrec-frontend   Up (healthy)   → http://localhost:3000
jobrec-backend    Up (healthy)   → http://localhost:8000  (OpenAPI: /docs)
jobrec-postgres   Up (healthy)   → localhost:55432  (db jobrec, user jobrec)
jobrec-ingest     Up             → 6-hour auto-ingest loop
smartfolio-db     ⚠️ unrelated project — ignore it
```

Daily ops (PowerShell, from repo root):

```powershell
docker compose up -d                 # start stack
docker compose ps                    # status
docker compose logs -f backend       # tail API logs
# .env change → MUST recreate (restart does NOT reload env_file):
docker compose up -d --force-recreate backend
# code change → auto hot-reloads, nothing to do
```

### 1.2 What is in the database (live counts, this session)

| Table | Rows | Notes |
|---|---|---|
| `users` | 208 | 205 JOB_SEEKER, 3 EMPLOYER, **0 ADMIN** (promote yourself to see `/admin`) |
| `profiles` | 205 | one per seeker |
| `jobs` | 319 | **313 adzuna** (272 on 09-24, 41 on 09-25) + 6 native |
| `companies` | 233 | employer upserts |
| `interactions` | 1,203 | clicks/applies/saves — feed M4 personalization |
| `recommendations` | 1,258 | served feed rows, each with propensity + strategy |
| `feedback` | 349 | explicit thumbs feedback |
| `applications` | 5 | tracker |
| `resumes` | 3 | parsed resumes (strict mode can hold failures) |
| `simulations` | 5 | career simulator runs |
| `skills` / `job_skills` / `skill_edges` | 120 / 650 / — | skill graph |
| `job_families` | 8 | family caps in MMR |
| `llm_usage`, `model_registry`, `system_config` | — | ops/observability |

**Job corpus reality check:** ingest lands ~95 rows/query (75 Adzuna + 20 Jobicy) but today every cycle ended `new_jobs: 0` — Adzuna repeats itself across cycles, Jobicy descriptions come back empty (`jobDesc` len 0 → all fail the `description_too_short` gate), Arbeitnow returns non-JSON, Remotive returns 0 results for the current query set. **Adzuna is the only provider actually contributing.**

### 1.3 Model / ML state

| Model | Artifact | State |
|---|---|---|
| M0 MiniLM embedder | in-process (CPU torch) | active, `EMBEDDING_BACKEND=minilm` |
| M1 skill2vec | artifact + registry | trained/promoted |
| M2 LightGBM ranklet | artifact + registry | **trained & eval-passed but IDLE** — `.env` says `RECOMMENDER_STRATEGY=deterministic` |
| M3 calibrator (isotonic) | artifact + registry | active |
| M4 preference learner | online, no artifact | active (bounded multiplicative update) |
| M5 Bradley-Terry | onboarding, deterministic fit | active |

Last eval `backend/ml/reports/eval-2026-09-24.json` — **all gates green**: NDCG@10 0.9455, extraction F1 0.9518, transfer F1 0.9829, ECE 0.0068, recall@20 0.8723.

### 1.4 Test & type state

- **257/257 backend tests green** (incl. 11 new autofill tests).
  ```powershell
  cd backend
  $env:DATABASE_URL='postgresql+psycopg://jobrec:change_me_in_production@localhost:55432/jobrec'
  $env:EMBEDDING_BACKEND='minilm'
  python -m pytest tests/ -q
  ```
- `npx tsc --noEmit` clean.
- OpenAPI: **58 paths**.
- Alembic head: **`0012_adzuna_currency_backfill`** (README still says `0011_ops` — stale).

### 1.5 LLM state

- `LLM_PROVIDER=gemini`, `LLM_MODEL=gemini-3.5-flash-lite`, `LLM_STRICT=true`, `EXPLAIN_LLM=true`.
- Timeout bounded: `LLM_TIMEOUT_SECONDS=120`, `request_options={"timeout": ...}` (commit `e3da0a8`).
- Free tier ~51 requests/day + ~20/min; under throttle latency hits 28s–519s. `EXPLAIN_LLM=false` conserves quota.
- **The LLM never assigns a score, never ranks, never runs SQL, never persists identity.** It writes prose and JSON *filters/structures* only, and validators reject anything that breaks a proof obligation.

### 1.6 Git state

- 19 commits, all local/unpushed. Latest `6afd53f`.
- **Blocker:** no `gh` CLI, no stored credentials, no SSH keys → cannot push yet. Fix: `winget install GitHub.cli` → `gh auth login`, then create repo `job-recommendation-system` on `aanyajain1215`.
- ⚠️ Working tree is **not** fully clean: `docs/DESIGN.md` has a 1-line edit (status line now says "LLM = Gemini (default)" instead of OpenAI). Commit or revert before pushing.

### 1.7 Known gaps / not-yet-built

1. No `POST /api/v1/jobs/fetch` — no "fetch fresh jobs now" button; only the 6h timer + CLI.
2. Hardcoded `localhost:8000` in `frontend/src/app/profile/page.tsx:483` (resume download link).
3. Dashboard "environment" card shows placeholder/fake values.
4. README says migration head `0011_ops`, actual is `0012`.
5. No OCR — image/PDF-scanned resumes yield no text (parse fails, strict mode shows Re-parse).
6. M2 ranklet idle behind `RECOMMENDER_STRATEGY`.
7. Prompts P3/P4/P5/P8/P10 defined but **unwired**.
8. The `ingest` container command lacks `--llm` (P2 keyword-scan instead of LLM structuring).
9. No rate limiting, no CI, no DB backups.
10. 0 admin users → `/admin` UI unusable until promoted.

---

## 2. Detailed Architectural Flow

### 2.1 The four containers and why each exists

```
┌─────────────────────┐    browser     ┌──────────────────────┐
│  jobrec-frontend    │ ─────────────► │   jobrec-backend     │
│  Next.js 16 / React │   HTTP :3000   │   FastAPI :8000      │
│  19 pages, RQ cache │ ◄───────────── │   auth·score·LLM·ML  │
└─────────────────────┘                └──────────┬───────────┘
                                                  │ SQLAlchemy
                                       ┌──────────▼───────────┐
                                       │   jobrec-postgres    │
                                       │  30 tables + pgvector│
                                       │  + FTS (GIN)         │
                                       └──────────▲───────────┘
                                                  │ upsert every 6h
                                       ┌──────────┴───────────┐
                                       │   jobrec-ingest      │
                                       │  Adzuna → 7 stages   │
                                       └──────────────────────┘
```

- **frontend**: UI only. Never talks to the DB. Talks to backend via `NEXT_PUBLIC_API_URL` / `API_INTERNAL_URL`.
- **backend**: the entire brain — auth, scoring, LLM lane, ML artifacts, all business logic. Mounts `./backend:/app` so code edits hot-reload.
- **postgres**: storage **and** computation — pgvector HNSW for KNN, GIN/`ts_rank_cd` for full-text, so retrieval happens *inside* the DB, not in Python.
- **ingest**: same image as backend, reuses live code, runs a shell loop: 4 rotating queries → pipeline → sleep 21600s.

### 2.2 Ingestion flow (7 stages) — how a job becomes searchable

```
Adzuna API (primary)
   │  fetch.py: fetch_all(query, pages=3, max_per_provider=75)
   │  isolated per provider — one failing provider never kills the run
   ▼
[1] FETCH      raw provider rows (adzuna / arbeitnow / remotive / jobicy)
   ▼
[2] CLEAN      strip HTML, normalize whitespace, coerce types
   ▼
[3] PARSE      salary text→intervals, location→geo, dates→timestamps
   ▼
[4] STRUCTURE  P2 LLM (opt-in --llm) or keyword scan → skills+importance,
               seniority, employment type
   ▼
[5] VALIDATE   quality gates: description ≥ 100 chars, canonical skill
               exists, dedupe by signature (external_id ∨ title+company)
               ├─ fail → logged in run report "problems" → row dropped
   ▼
[6] EMBED      MiniLM → vector(384) → HNSW index
   ▼
[7] UPSERT     jobs + companies + job_skills + job_families (8 families)
   ▼
run report JSON: fetched/cleaned/parsed/structured/gate_failed/dup_skipped/
                 new_jobs/updated_jobs/embedded/provider_errors
```

Same 7 stages run **offline** against `ml/data/golden/postings.jsonl` (100 frozen rows) — that's how CI/eval stays deterministic while production is live.

### 2.3 Serving flow (recommendation pipeline) — what happens on every feed load

```
GET /api/v1/recommendations (user, token)
   │
   ├─ cold start? (no interactions / incomplete profile)
   │     └─► cold_start_score = max(30, experience×0.5 + completeness rubric)
   │         strategy = "deterministic", COLD_STRATEGY_LABEL
   │
   ▼
[1] CANDIDATE GENERATION — 3 independent legs
   ├─ KNN leg:  pgvector cosine on profile embedding   (try/except)
   ├─ FTS leg:  websearch_to_tsquery + ts_rank_cd      (try/except)
   └─ skill leg: exact skill-set overlap               (try/except)
   ▼
[2] RRF FUSION — Reciprocal Rank Fusion, k = 60
       score(d) = Σ 1/(60 + rank_i(d))   over the legs that survived
   (order-only → legs with incomparable scales fuse safely;
    a dead leg degrades to 2-leg or 1-leg with no recalibration)
   ▼
[3] SCORING — scoring.score_pair(), 8 components, Σ = 1
       semantic .30 | skill .25 | experience .15 | education .10
       project .05 | location .05 | salary .05 | interest .05
       × per-component affinity factor max(0, 1 + 0.3·affinity)
       → combine() = weighted sum, clamped [0,100]
       neutral priors fill every missing input (never imputed, never NaN)
   ▼
[4] RERANK — rerank.rerank()
       strategy ∈ {deterministic | ltr_blend}
       ltr_blend: Δ = clamp(0.35 × (LGBM − deterministic), ±15)
       → learned model gets 35% of its opinion, ±15 max authority
       → response honestly reports `strategy` + `delta_note`
   ▼
[5] MMR DIVERSITY — mmr.mmr(), λ = 0.7
       MMR = 0.7·rel_norm − 0.3·(cos+1)/2      (both terms shifted to [0,1])
       + family cap (≤ N per job family, 8 families)
   ▼
[6] EXPLANATION — explanation.build_explanation()
       contribution_k = weight_k × component_k
       Σ contributions ≈ final score (validated within 0.15)
       bands: ≥85 strong / ≥70 good / ≥50 partial / else weak
       optional P6 LLM polish (EXPLAIN_LLM=true) → digit-multiset check
   ▼
[7] EXPLORATION — 1 slot in 6
       sha256(user_id : date) → [0,1) < 1/6  ⇒ inject a random-ish job
       propensity 0.1667 logged on that row (off-policy eval ready)
       never slot 0 → always stable top result
   ▼
[8] PERSIST recommendations rows (strategy, propensity, model_version)
   ▼
Response { items[], strategy, personalization_note, model_version, ... }
```

### 2.4 The guarded LLM lane (side channel, never in the math)

```
feature request
   │
   ├─ deterministic core computes the number
   │
   └─ optional LLM call (timeout 120s, LLM_STRICT gate)
         │
         ├─ provider gemini (google-generativeai, model gemini-3.5-flash-lite)
         ▼
      raw text/JSON
         ▼
      VALIDATORS (the wall)
         ├─ digit multiset: Counter(digits(out)) == Counter(digits(src))
         ├─ evidence span: every claimed fact must exist in source text
         ├─ whitelist: only ALLOWED_FIELDS survive (P7)
         ├─ schema: Pydantic enum/int coercion
         └─ identity honesty: LLM name/phone must be verbatim in source
         ▼
      ├─ pass  → polished prose ships to UI
      └─ fail  → LLM_STRICT=true  ⇒ HTTP 502 (fail loud, no silent fallback)
                 LLM_STRICT=false ⇒ fall back to deterministic prose
```

### 2.5 Auth flow

```
POST /api/v1/auth/register | /login  → JWT (HS256)
frontend stores token → React Query + auth-context
every protected call → Authorization: Bearer <token>
backend deps.py → get_current_user → role check
roles: JOB_SEEKER | EMPLOYER | ADMIN
  seeker: profile, feed, apply, gap, roadmap, simulator
  employer: POST/PUT/DELETE /jobs, view own applications
  admin: /admin/* (skills merge, duplicates, llm-usage, parse-failures, config, models)
```

---

## 3. User Flow Diagrams

### 3.1 Job seeker — first run (onboarding → feed)

```
/ (landing)
  └─► /register  {email, password}
        └─► /onboarding
              ├─ Q1..Q3  career direction (M5 Bradley-Terry picks)
              │           3 picks → θ = gradient-ascent fit → softmax(θ)
              │           L2-anchored to global prior ⇒ tilt, never extremize
              ├─ Q4      skills / experience / education
              └─ Q5      salary expectation, location, remote pref
                    └─► profile saved (Σ=1 weight vector seeded global)
                          └─► /recommendations  (cold-start scoring)
                                └─► /jobs/[id]  detail
                                      ├─ Save ─────► /saved
                                      ├─ Apply ─────► /tracker  (status: applied)
                                      ├─ 👍/👎 ─────► feedback → M4 weight update
                                      └─ Dismiss ───► removed from feed
```

### 3.2 Job seeker — returning user (the main loop)

```
/login ─► /dashboard
            ├─► /recommendations   RRF→score→rerank→MMR→explain→explore
            │        └─ each card shows: score, contribution breakdown, band
            ├─► /jobs              FTS search + filters (location, remote,
            │        │              salary, skills[], family)
            │        └─ or NL search bar ──► /jobs?q=… (mode: llm|fts)
            ├─► /gap/[jobId]       "why don't I match" — same skill_match()
            │        └─► /roadmap  ordered skills + hours + resources
            │                 └─► mark complete → gap re-scores live
            ├─► /careers           adjacent career paths (0.7·overlap + 0.3·semantic)
            ├─► /simulator         "what if I learned X" → projected score delta
            ├─► /resume-optimize   P9 bullet critique
            ├─► /tracker           application statuses
            ├─► /saved             saved jobs
            └─► /settings          weights, personalization deltas, shrinkage %
```

### 3.3 Resume auto-fill flow (the feature just shipped)

```
/profile
   │
   ├─ [Manual path — unchanged]
   │    type into any field ─► Save ─► profile columns updated
   │
   └─ [Auto-fill path]
        Upload/choose resume ─► POST /profiles/{id}/parse
              ├─ text extract (PDF/txt; no OCR yet)
              ├─ P1 LLM → structured JSON + evidence spans
              │    └─ identity honesty guard:
              │         name/phone must appear VERBATIM in source
              │         else DROPPED (never persisted)
              ├─ regex fallback if LLM unavailable/strict-failed
              └─ result stored in parsed_resume_data["autofill"]
                    └─ frontend polls (3-min deadline) ─► fills ONLY
                       fields the parser actually FOUND
                       ├─ your manual entries for other fields survive
                       ├─ identity fields NEVER auto-save
                       └─ [Review] ─► [Save] ─► columns persisted
        on failure ─► parse_status="failed" ─► [Re-parse] button
```

### 3.4 Natural-language search flow

```
user types: "remote python jobs in Bengaluru paying above 15 lakh"
   │
   ▼
GET /api/v1/jobs/nl?q=…
   │
   ├─ P7 LLM → JSON {keywords, location, remote_only, min_salary, skills,…}
   │    ├─ whitelist drop (ALLOWED_FIELDS)
   │    ├─ Pydantic enum/int coercion
   │    ├─ skill canonicalization (same normalizer as structured filters)
   │    └─ ANY failure (no key / timeout / strict 502 / bad schema)
   │          └─► mode="fts": whole string becomes a full-text query
   ▼
build_filtered_query()  ── SQL with WHERE over validated filters only
   ▼
fetch 200 candidates ─► hybrid_rank() = RRF(k=60) over
       (a) ts_rank_cd  (b) pgvector KNN on e_job  (c) skill-set match count
   tie-break: recency → job id   (fully deterministic)
   ▼
response { items, mode, parsed_filters, q }
   UI renders parsed_filters as EDITABLE CHIPS
   → the user, not the LLM, is the final authority
```

### 3.5 Employer flow

```
/register (role=EMPLOYER) ─► create Company (upsert)
   └─► POST /jobs  {title, description, skills, salary, location, family…}
         ├─ skill graph validation (canonical skill must exist)
         ├─ embedding computed
         └─ appears in seeker feed via the SAME pipeline
   └─► /dashboard(employer)
         ├─ my jobs ─► PUT /jobs/{id} (edit)  DELETE (close)
         └─ applicants ─► GET /employer/applications
               └─ update status: applied → screening → interview → offered/hired
```

### 3.6 Admin flow (needs ADMIN promotion first)

```
SQL> UPDATE users SET role='ADMIN' WHERE email='you@x.com';  + re-login
   └─► /admin
         ├─ Score weights editor   PUT /admin/config  (Σ=1 validated)
         ├─ LLM usage              GET /admin/llm-usage  (calls/fails/latency per prompt)
         ├─ Duplicate jobs         GET /admin/jobs/duplicates (cos≥0.92 ∧ title≥0.60)
         │                          └─ human decides; read-only merge
         ├─ Parse failures         GET /admin/parse-failures → POST …/retry
         ├─ Model registry         GET /admin/models (M0–M5 active versions)
         └─ Skill merge            POST /admin/skills/merge (aliases+edges+affinities moved)
```

### 3.7 Ingestion ops flow (background, no human)

```
jobrec-ingest container, every 6h:
  python developer ─┐
  data analyst      ├─► fetch_jobs_live.py --upsert  ×4
  devops engineer   │      (7 stages each)
  ml engineer       ─┘
  └─► sleep 21600s ─► repeat
  stop: docker compose stop ingest
```

---

## 4. Tech Inventory — what we used, when, and where

### 4.1 Frontend

| Tech | Version | Where used |
|---|---|---|
| Next.js | 16.3.4 | `frontend/` — App Router, 19 pages (`src/app/**/page.tsx`) |
| React | 19.2.8 | client components, `"use client"` pages |
| Tailwind CSS | 4.x | all styling, `frontend/src/app/globals.css` |
| TanStack React Query | — | data fetching/caching: `frontend/src/lib/api.ts` + hooks |
| lucide-react | — | icons across all pages |
| auth-context | custom | `frontend/src/lib/auth-context.tsx` — JWT storage, role gating |

**Pages:** `/`, `/login`, `/register`, `/onboarding`, `/dashboard`, `/recommendations`, `/jobs`, `/jobs/[id]`, `/jobs/new`, `/gap/[jobId]`, `/roadmap`, `/careers`, `/simulator`, `/resume-optimize`, `/profile`, `/saved`, `/tracker`, `/settings`, `/admin`.

### 4.2 Backend core

| Tech | Version | Where used |
|---|---|---|
| FastAPI | 0.128 | `backend/app/main.py`, 22 routers in `app/api/` |
| SQLAlchemy | 2.0.46 | `backend/app/models/` (18 model files) |
| Alembic | — | 12 migrations, head `0012_adzuna_currency_backfill` |
| Pydantic v2 | — | schemas, and the **whitelist wall** for LLM output |
| psycopg | — | Postgres driver, `DATABASE_URL` |
| pgvector | — | `vector(384)` + HNSW index on `jobs.embedding` |
| PostgreSQL FTS | — | `search_vector` GIN + `websearch_to_tsquery` + `ts_rank_cd` |
| JWT (HS256) | — | `app/core/security.py`, roles in `deps.py` |

**API routers:** `auth, profiles, jobs, search, recommendations, interactions, gap, roadmap, careers, project_mapping, simulate, preferences, onboarding, applications, feedback, resume_optimize, skills, admin, health` → **58 OpenAPI paths**.

### 4.3 ML / math stack

| Tech | Version | Where / when used |
|---|---|---|
| PyTorch (CPU) | — | MiniLM embeddings, no GPU anywhere; `EMBEDDING_BACKEND=minilm` |
| sentence-transformers MiniLM | — | M0 — job/profile/resume vectors at ingest + query time |
| LightGBM (LambdaRank) | — | M2 ranklet `ml/train_ranklet.py`; idle until `RECOMMENDER_STRATEGY=ltr_blend` |
| scikit-learn | — | isotonic calibrator M3 `ml/calibrate.py`, metrics in `ml/metrics.py` |
| gensim (word2vec/skip-gram) | — | M1 skill2vec `ml/train_skill2vec.py` |
| rapidfuzz | — | fuzzy title/company dedupe + normalizer |
| NumPy | — | score vectors, Bradley-Terry fit |

**Training entrypoint:** `backend/ml/train.py --all` → M1 → datasets → M2 → M3, registers to `model_registry`, promotes **only** if gates pass (NDCG ≥ baseline, F1 ≥ 0.85/0.80, ECE ≤ 0.10, recall@20 ≥ 0.75).

### 4.4 Job data sources

| Provider | Role | Status today |
|---|---|---|
| **Adzuna** | PRIMARY (`ADZUNA_APP_ID/KEY`, country=in) | ✅ working — 313/319 jobs |
| Arbeitnow | secondary, keyless | ❌ non-JSON response |
| Remotive | secondary, keyless | ⚠️ 0 results for current queries |
| Jobicy | secondary, keyless | ❌ `jobDesc` empty → fails length gate |

Config: `.env` lines 27–31 (`ADZUNA_APP_ID=e719038b`, `ADZUNA_COUNTRY=in`, `INGEST_HTTP_TIMEOUT=20`, `INGEST_DELAY_SECONDS=0.5`), `INGEST_INTERVAL_SECONDS=21600`.

### 4.5 LLM layer

| Item | Detail |
|---|---|
| Provider | Gemini (free tier) via `google-generativeai` — **note: deprecated SDK upstream** |
| Model | `gemini-3.5-flash-lite` |
| Flags | `LLM_STRICT=true`, `EXPLAIN_LLM=true`, `LLM_TIMEOUT_SECONDS=120` |
| Prompt catalog | `app/services/llm/prompts.py` — **P1–P10** |
| Validators | `app/services/llm/validators.py` — digit-multiset, span, whitelist, schema |

| Prompt | Wired? | Purpose | Validator |
|---|---|---|---|
| P1 | ✅ live | resume → structured + spans | span, skill-token |
| P2 | ✅ live (needs `--llm`) | JD → structured requirements | span, skill-token |
| P3 | ❌ unwired | (defined) | — |
| P4 | ❌ unwired | (defined) | — |
| P5 | ❌ unwired | (defined) | — |
| P6 | ✅ live | explanation polish | **digit-multiset** |
| P7 | ✅ live | NL query → SearchFilters | field whitelist |
| P8 | ❌ unwired | (defined) | — |
| P9 | ✅ live | resume bullet critique | structure |
| P10 | ❌ unwired | skill prereq edge proposals | skill-token |

### 4.6 Script / ops tooling

| Script | When to run | What it does |
|---|---|---|
| `scripts/fetch_jobs_live.py --query X --upsert` | manual / 6h timer | full 7-stage live ingest |
| `… --offline` | CI / eval | golden corpus through identical stages |
| `scripts/seed_synthetic_users.py` | demo bootstrap | 200 deterministic seekers (seed 1729), `--delete` to purge |
| `scripts/seed_jobs.py` / `seed_canonical.py` | setup | canonical skills + sample jobs |
| `scripts/embed_backfill.py` | after big ingests | recompute missing embeddings |
| `ml/train.py --all` | weekly/manual | retrain + gated promotion |

### 4.7 Data files

| File | Rows | Purpose |
|---|---|---|
| `ml/data/golden/postings.jsonl` | 100 | frozen job postings for offline ingest |
| `ml/data/golden/resumes.jsonl` | 50 | extraction F1 eval |
| `ml/data/golden/relevance_pairs.jsonl` | 21 | graded relevance → NDCG |
| `ml/data/golden/transfer_pairs.jsonl` | 228 | skill transfer labels → skill2vec F1 |
| `ml/datasets/train.jsonl` | 960 | temporal-split ranklet training |
| `ml/datasets/test.jsonl` | 240 | held-out test |
| `ml/reports/eval-2026-09-24.json` | — | all gates green |

---

## 5. Complete Fallback List

**Principle:** *every* external/learned/optional dependency has a documented deterministic degradation, and the response **tells the caller which path actually ran**. The deterministic core has **no** fallback — it cannot fail silently because it has nothing to fail into.

### 5.1 Serving / ranking fallbacks

| # | Failure | Fallback | How you can tell |
|---|---|---|---|
| F1 | pgvector KNN leg errors | drop it; RRF over remaining legs | log `"KNN candidate leg failed"` |
| F2 | FTS leg errors | drop it; RRF over remaining | log `"FTS candidate leg failed"` |
| F3 | skill leg errors | drop it | log `"skill candidate leg failed"` |
| F4 | all legs dead / cold user | cold-start score `max(30, exp×0.5 + completeness)` | `strategy=deterministic`, `COLD_STRATEGY_LABEL` |
| F5 | ranklet artifact missing | pure deterministic scoring | `strategy: "deterministic"` |
| F6 | ranklet loaded but weak | `ltr_blend` with Δ clamped ±15 | `strategy: "ltr_blend"` + `delta_note` |
| F7 | calibrator missing | raw `score/100`, **different bands** (0.50/0.75 vs 0.60/0.80) | readiness path |
| F8 | embedder unavailable (anywhere) | `except: continue` — proceed unembedded | degraded ranking, still correct |
| F9 | project cards / detached profile | skip cards, keep feed | `except … project cards optional` |
| F10 | corrupt `system_config` weights row | code defaults, Σ=1 | log + defaults |

### 5.2 NL search fallbacks

| # | Failure | Fallback | How you can tell |
|---|---|---|---|
| F11 | no LLM key / provider error | whole query → FTS keywords | `mode: "fts"` |
| F12 | LLM returns bad schema / bad enums | coerce; if hopeless → FTS | `mode: "fts"` |
| F13 | LLM returns unknown fields | **dropped by whitelist** (never passed to SQL) | logged `P7 dropped non-whitelisted fields` |
| F14 | `LLM_STRICT=true` + P7 violation | **HTTP 502, fail loud** | strict trial |
| F15 | embedding KNN fails inside hybrid_rank | RRF over FTS + skill legs | log |

### 5.3 LLM feature fallbacks

| # | Failure | `LLM_STRICT=false` (normal) | `LLM_STRICT=true` (trial) |
|---|---|---|---|
| F16 | resume parse fails | regex fallback extracts name/phone/skills | `parse_status="failed"` + Re-parse button |
| F17 | identity unverifiable (LLM invented name/phone) | field dropped, rest kept | same — **identity guard is always on** |
| F18 | explanation polish fails digit check | ship the deterministic explanation | HTTP 502 on that call |
| F19 | Gemini timeout (120s) / quota 429 | deterministic prose | HTTP 502 |
| F20 | poll deadline (3 min) for autofill | UI stops waiting, keeps manual entry | same |
| F21 | NL search P7 fails | `mode=fts` | HTTP 502 |

### 5.4 Ingestion fallbacks

| # | Failure | Fallback | Evidence |
|---|---|---|---|
| F22 | one provider down | other providers still land (`fetch_all` never raises) | `provider_errors` in run report |
| F23 | all providers down | run fails soft, next cycle retries | `"all providers failed"` message |
| F24 | quality gate fail (short desc / no skill) | row dropped + logged in `problems` | 20 Jobicy rows/day dropped this way |
| F25 | duplicate signature | skipped, counted | `dup_skipped` |
| F26 | keyless feed ignores paging | stop on repeated `external_id` | `fetch_all` comment |
| F27 | no `--llm` on P2 stage | keyword-scan structuring (ingest container today) | ingest command |

### 5.5 Model degradation contracts (M0–M5)

| Model | If it disappears |
|---|---|
| M0 embedder | FTS-only retrieval (F2/F11) |
| M1 skill2vec | curated taxonomy edges → fixed transfer credit |
| M2 ranklet | deterministic scorer (F5) — **and it must beat that scorer to ship at all** |
| M3 calibrator | raw score with looser bands (F7) |
| M4 preference learner | global Σ=1 weights (shrinkage → 100% global when n=0) |
| M5 Bradley-Terry | global prior weights (L2 anchor means 0 picks ≈ global) |

**There is no fallback for the deterministic core** — by design. That is what makes every number reproducible and explainable.

---

## 6. What is NL Search?

**NL search = Natural-Language search.** Instead of ticking filter boxes, you type a normal sentence and the system converts it into *structured database filters*, then runs the regular indexed query.

### The one-sentence version

> You type **"remote python jobs in Bengaluru paying above 15 lakh"** → an LLM turns that into the JSON `{"remote_only": true, "skills": ["python"], "location": "Bengaluru", "min_salary": 1500000}` → that JSON is validated against a whitelist and handed to the *same* SQL query builder the filter UI uses → results are ranked by RRF over full-text, embeddings, and skill overlap → and the parsed filters come back as **editable chips** so you can fix anything the LLM got wrong.

### Endpoint & code path

- **Endpoint:** `GET /api/v1/jobs/nl?q=…&page=&page_size=`
- **Code:** `backend/app/api/jobs.py:354 nl_search_jobs()` → `backend/app/services/nl_search.py` → prompt **P7** in `app/services/llm/prompts.py`

### Step by step

1. **Parse** — `nl_search.parse_query(q)`: call the LLM with P7 asking for *filters only*.
2. **Sanitize** — `sanitize()` keeps only `ALLOWED_FIELDS = (keywords, location, remote_only, employment_type, experience_level, min_salary, skills)`. Anything else is dropped, so an LLM cannot inject `SELECT` or a rogue field.
3. **Coerce** — Pydantic validates enums (`EmploymentType`, `ExperienceLevel`) and forces `min_salary` to int.
4. **Canonicalize skills** — "js" → `javascript` through the *same* normalizer the structured filter UI uses, so both paths agree.
5. **Build SQL** — `build_filtered_query()` produces a normal SQLAlchemy query with WHERE clauses. **The LLM never sees or writes SQL.**
6. **Fetch 200 candidates** (`CANDIDATE_CAP`), then **`hybrid_rank()`**: RRF with `k = 60` over
   - (a) Postgres `ts_rank_cd` full-text order,
   - (b) pgvector KNN order on the job embedding,
   - (c) skill-set match count.
   Tie-break: recency, then job id → fully deterministic output for the same inputs.
7. **Echo** — response returns `mode` (`"llm"` or `"fts"`), `parsed_filters` (the chips), and your original `q`.

### Why it's designed this way (the safety story)

- **The LLM produces data, never actions.** It returns a JSON object; whitelist → schema → canonicalize → SQL. There is no code path where model text reaches the database as text.
- **The user is the final authority.** `parsed_filters` render as editable chips — if the model misread "above 15 lakh" you can delete or correct the chip without retyping.
- **Honest degradation.** If the key is missing, quota is exhausted, or strict mode rejects the output, `mode: "fts"` and your whole sentence is treated as a keyword query — the UI shows you that it fell back, it doesn't pretend.
- **It ranks like everything else.** Same RRF, same deterministic tie-breaks as the recommendation path — one ranking law across the product.

### NL search vs. regular search

| | `GET /jobs?search=…` | `GET /jobs/nl?q=…` |
|---|---|---|
| Input | keyword + explicit filter params | one free sentence |
| Parsing | none — you set the filters | LLM (P7) sets them for you |
| Ranking | FTS order (+filters) | RRF: FTS + embeddings + skills |
| Failure mode | n/a | degrades to FTS |
| LLM required | no | yes (but degrades gracefully) |

---

## 7. Where things stand — next actions

1. **You:** try the autofill at http://localhost:3000/profile (free tier can be slow → use Re-parse).
2. **GitHub:** install `gh` + `gh auth login` → create `job-recommendation-system` on `aanyajain1215` → push the 19 commits (after resolving the `docs/DESIGN.md` one-liner).
3. **P1 leftovers on your go-ahead:** `POST /api/v1/jobs/fetch` + "Fetch jobs" UI, hardcoded `localhost:8000` in `profile/page.tsx:483`, fake dashboard env card, README migration head.
4. **Data growth:** widen the 4-query ingest rotation; fix Jobicy (`jobDesc` empty → try `jobExcerpt`) and investigate Arbeitnow's non-JSON response.
5. **Backlog:** faculty brief, M0 stretch (rate limiting, dup auto-merge, online metrics), wire P3/P4/P5/P8/P10, `--llm` in the ingest container.
