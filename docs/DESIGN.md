# JobRec — Technical Design
## AI-Powered Job Recommendation & Career Path Intelligence System

**Status:** v1.2 — decisions locked: LLM = OpenAI, stack = Next.js + FastAPI, primary job API = **Adzuna**, corpus = live-first + **preprocessing pipeline (§20.1)**, synthetic interaction bootstrap confirmed. Pending: M5 scope.
**Scope:** Full-system design: data model, deterministic scoring engine, trained models, LLM layer, APIs, UI, evaluation, file-by-file implementation plan.

---

## Table of Contents

1. [How to read this document](#0-how-to-read-this-document)
2. [Alignment with the original plan](#1-alignment-with-the-original-plan)
3. [Declared deviations & assumptions](#2-declared-deviations--assumptions)
4. [Guiding principles](#3-guiding-principles)
5. [System architecture](#4-system-architecture)
6. [Data model](#5-data-model)
7. **[The Model Suite — real, trained artifacts](#6-the-model-suite--real-trained-artifacts)**
8. [Deterministic Scoring Engine (Gap-to-Opportunity core)](#7-deterministic-scoring-engine)
9. [Skill taxonomy, normalization & Skill Gap Engine](#8-skill-taxonomy-normalization--skill-gap-engine)
10. [Career Roadmap Generator](#9-career-roadmap-generator)
11. [What-If Career Simulator](#10-what-if-career-simulator)
12. [Alternative Career Discovery](#11-alternative-career-discovery)
13. [Explainability layer](#12-explainability-layer)
14. [Resume Improvement Engine](#13-resume-improvement-engine)
15. [Project-to-Job Mapping](#14-project-to-job-mapping)
16. [LLM Layer — providers, prompts, safety](#15-llm-layer--providers-prompts-safety)
17. [Feedback Loop & Personalization Model](#16-feedback-loop--personalization-model)
18. [Search: structured + NL + hybrid retrieval](#17-search-structured--nl--hybrid-retrieval)
19. [API surface](#18-api-surface)
20. [Frontend plan](#19-frontend-plan)
21. [Pipelines & batch jobs](#20-pipelines--batch-jobs)
22. [Evaluation plan](#21-evaluation-plan)
23. [Security, safety & ops](#22-security-safety--ops)
24. **[File-by-file implementation plan](#23-file-by-file-implementation-plan)**
25. [Milestones, scope & demo script](#24-milestones-scope--demo-script)
26. [Risks & mitigations](#25-risks--mitigations)
27. [Open questions](#26-open-questions)

---

## 0. How to read this document

- **§1** proves 1:1 traceability against the original 25-point plan.
- **§6 and §7 are the heart**: what is *trained* (a real model) vs. what is *computed deterministically* (scores) vs. what the *LLM writes* (prose only).
- **§23** is the build order — new files vs. modified files, phase by phase.
- Numbers in this doc (weights, thresholds, hours) are **config defaults**, all overridable.

---

## 1. Alignment with the original plan

| Original plan section | Design section | Status |
|---|---|---|
| 1. Core objective (10 user capabilities) | §4 flows, §19 pages | ✅ covered |
| 2. Career Gap-to-Opportunity Engine (10 match dimensions, deterministic) | §7 scoring engine, §8 gap engine | ✅ core of design |
| 3. LLM resume understanding (structured JSON + evidence) | §15 LLM layer, §5 `resumes` table | ✅ + evidence validator |
| 4. JD understanding + skill normalization/canonical taxonomy | §8 taxonomy, §15 job-extraction prompt | ✅ |
| 5. Semantic matching, embeddings, **one** vector DB | §4, §6-M0, §5 (`pgvector`) | ✅ pgvector only |
| 6. Hybrid weighted score, configurable, LLM never scores | §7 | ✅ exact weights adopted |
| 7. Skill gap classes: strong/partial/missing/transferable | §8 | ✅ + trained skill2vec |
| 8. AI career roadmap with phases | §9 | ✅ DAG-ordered, LLM phrasing |
| 9. What-If Career Simulator (deterministic deltas) | §10 | ✅ counterfactual engine |
| 10. Alternative career discovery with calculated overlap | §11 | ✅ role-family model |
| 11. Explainable recommendation (why / concerns / action) | §12 | ✅ explanation contract |
| 12. Resume Improvement Engine (no fabrication) | §13 | ✅ grounding validator |
| 13. Project-to-Job mapping | §14 | ✅ deterministic overlap |
| 14. Dashboard components | §19 | ✅ |
| 15. Search & filtering + NL query → structured filters (no LLM SQL) | §17 | ✅ whitelisted filter JSON |
| 16. Data architecture (table list, pgvector) | §5 | ✅ full table mapping |
| 17. Backend architecture stack | §2 deviation D1 | ⚠️ kept current stack (rationale below) |
| 18. LLM safety rules (7 "must nots") | §15 safety rails, §22 | ✅ enforced by validators |
| 19. Recommendation feedback loop (7 reasons, resettable) | §16 | ✅ + learned weight model |
| 20. Application tracking + analytics (no causal claims) | §19, §18 | ✅ status mapping noted |
| 21. Admin panel (skill merge, dup jobs, LLM usage, failed parsing) | §22 | ✅ |
| 22. UI/UX — 14 pages | §19 | ✅ page-by-page |
| 23. Example user flow | §24 demo script | ✅ reproduced as acceptance test |
| 24. Evaluation metrics (P@K, R@K, NDCG, MRR, extraction F1, …) | §21 | ✅ per-model harness |
| 25. Final differentiator combination | §3 principles + §6 | ✅ |

---

## 2. Declared deviations & assumptions

| # | Original plan says | This design does | Rationale |
|---|---|---|---|
| D1 | React + TypeScript / Node.js + Express/NestJS | **Keep Next.js (App Router) + FastAPI** (already built, tested, dockerized) | Plan's *intent* (typed SPA frontend, REST backend, Postgres+pgvector, JWT) is fully satisfied. Rewriting a working stack burns days and risks regressions. `frontend/AGENTS.md` rules apply to all frontend code. |
| D2 | Validate LLM responses with **Zod** | **Pydantic v2** is the authoritative validator (backend is Python); frontend keeps strict TS types; `zod` optional at the client boundary | LLM calls happen server-side only (§15); the trust boundary is the backend. |
| D3 | LLM: "OpenAI API or another configurable provider" | **Provider abstraction with OpenAI as default** (`OPENAI_API_KEY`, model via `LLM_MODEL` env); Gemini adapter retained behind the same interface | *Decided:* OpenAI is the primary provider; abstraction keeps the door open. |
| D4 | `FinalScore` example weights | **Adopted verbatim as defaults** (§7), stored in config | Plan explicitly demands configurable weights. |
| D5 | Table list includes `job_requirements`, `user_skills`, … | Existing `job_skills` / `profile_skills` **are** those tables (better: structured, weighted); new tables added for the rest | Schema continuity; no parallel duplicates. |
| D6 | Application statuses: Saved→Applied→Interview→Offer→Rejected | Existing enum `applied/viewed/shortlisted/interview/rejected/offer` **+ add `saved`**; UI maps display labels to it | Existing data & endpoints preserved; richer than plan. |
| D7 | Plan implies LLM central to matching | Plan itself (§6, §18) forbids LLM scoring — design makes the split **structural**: deterministic core, LLM periphery, *trained models* in between | This is also the answer to "a real model, not something that already exists" (§6). |

**Assumptions:** an OpenAI API key is available for dev/demo (regex/template fallbacks exist for every LLM path); single-region deploy via the existing `docker-compose.yml`; salary expectations may be in a different currency than postings → deterministic FX table (admin-editable, default static rates) used by `SalaryMatch`.

---

## 3. Guiding principles

1. **Deterministic core, LLM periphery.** Scores, matching, filtering, eligibility, roadmaps' *ordering and effort numbers*, simulator deltas → pure Python functions with unit tests. Explanations, roadmap prose, extraction, NL parsing → LLM, schema-validated, evidence-grounded.
2. **Every number is reproducible.** Same profile + same job + same config ⇒ byte-identical score, forever (simulator and caching depend on this).
3. **Every extracted fact has evidence.** A skill with no verifiable span in the resume/JD is rejected or explicitly marked `unverified` — never silently believed.
4. **One vector store:** PostgreSQL + pgvector. One embedder by default (§6-M0).
5. **Models are versioned artifacts**, registered in the DB, evaluable, rollback-able — not notebook experiments.
6. **The user owns their preferences.** Personalization is bounded, explained, and resettable in one click (§16).
7. **Hypothetical ≠ real.** Simulator skills live in a shadow context; they can never leak into `profile_skills`.

---

## 4. System architecture

```
┌─────────────────────────────  Next.js frontend  ─────────────────────────────┐
│ Landing · Auth · Resume Upload · Profile Builder · Dashboard · Recommend-   │
│ ations · Job Detail(+Gap) · Skill Gap · Roadmap · Simulator · Resume        │
│ Optimizer · Saved · Tracker · Settings · Admin                              │
└───────────────────────────────┬──────────────────────────────────────────────┘
                                │ REST + JWT (existing auth)
┌───────────────────────────────▼──────────────────────────────────────────────┐
│ FastAPI (app/api/*)                                                          │
│  ┌──────────────┐ ┌───────────────┐ ┌──────────────┐ ┌───────────────────┐   │
│  │ Auth/Roles   │ │ Profile+Resume│ │ Jobs/Search  │ │ Recommendations   │   │
│  └──────────────┘ └──────┬────────┘ └──────┬───────┘ └─────────┬─────────┘   │
│                          │                 │                    │             │
│  SERVICES (app/services) v                 v                    v             │
│  ┌─────────────────────────────────────────────────────────────────────┐     │
│  │ DETERMINISTIC CORE                    │ LLM PERIPHERY (provider-abs)│     │
│  │  scoring.py      (8 components)       │  resume_parser (exists)     │     │
│  │  gap_engine.py   (4-class compare)    │  job_understanding.py       │     │
│  │  skill_graph.py  (transfer/prereq)    │  explain.py                 │     │
│  │  roadmap.py      (DAG order+effort)   │  roadmap_prose              │     │
│  │  simulator.py    (counterfactual)     │  resume_improve.py          │     │
│  │  personalization.py (weight model)    │  nl_search.py → filter JSON │     │
│  │  embeddings.py   (MiniLM 384d)        └─────────────────────────────┘     │
│  │  rerank.py       (LightGBM + isotonic ← trained in backend/ml/)           │
│  └─────────────────────────────────────────────────────────────────────┘     │
└───────────────┬─────────────────────────────────────┬────────────────────────┘
                │                                     │
     ┌──────────▼──────────┐              ┌───────────▼────────────┐
     │ PostgreSQL + pgvector│              │ Model registry (DB)    │
     │ users profiles jobs  │              │ + artifacts/*.joblib   │
     │ skills graph gaps    │              │ + LLM usage logs       │
     │ paths sims feedback  │              └────────────────────────┘
     └─────────────────────┘
```

### Canonical flows

**A. Recommendation (GET /recommendations)**
1. Load profile + shadow-free context → `embeddings.py` ensures profile embedding is fresh (`embedding_updated_at` invalidation on any profile/skill change).
2. **Candidate generation:** pgvector KNN (top 200 by semantic) ∪ FTS `websearch_to_tsquery` (top 200) ∪ required-skill-match query → **Reciprocal Rank Fusion** → top ~100 candidates. (Replaces today's "load *all* jobs and TF-IDF per request".)
3. **Score** each candidate with the deterministic engine (§7) using graph-aware skill matching (§8).
4. **Blend** with trained model if `strategy=ltr_blend` (§6-M2): `final = (1−α)·det + α·calibrated`, α default 0.0 until eval gate passes, then 0.35; model contribution clamped to ±15 pts around deterministic score (explainability guardrail).
5. **Re-rank:** MMR diversity (λ=0.7, ≤3 per job family in top-10) + 1 exploration slot (1-in-6, propensity logged in `interactions.metadata`).
6. **Explain:** build explanation contract (§12) from components — templated prose always; optional LLM polish (flag-gated, cached).

**B. Resume upload** → extract text (exists) → LLM structured JSON **with evidence spans** → *evidence validator* → canonicalize skills (§8) → upsert profile (+ education/experience/projects/certifications tables) → enqueue embedding backfill.

**C. Simulator (POST /simulate)** → clone scoring context → apply mutation (add skill, change salary/location/target role) → re-run *the same* scoring functions → return per-job deltas + band changes → persist `simulation_history`. Never writes real tables.

**D. NL search** → LLM → `SearchFilters` JSON (Pydantic, whitelisted enums/fields) → existing SQL query builder (extended). No LLM-generated SQL, ever. Semantic-only queries → embed → hybrid KNN+FTS.

---

## 5. Data model

### 5.1 Existing tables (kept, extended)

| Table | Change |
|---|---|
| `users` | + `is_admin` covered by existing `role` enum (ADMIN exists) |
| `profiles` | **+ `expected_salary_min/max/currency`, `target_job_family_id`, `preferred_work_mode`, `career_interests JSONB`, `preferred_locations TEXT[]`**; keep `education`/`work_experience` JSONB as *resume snapshot cache*; `embedding Vector(384)` **now actually populated** |
| `jobs` | + `family_id` (job family), `industry` via company, + **`source`, `external_id`, `external_url`** (imported live jobs; dedupe on `(source, external_id)`); `embedding Vector(384)` populated; `search_vector` (exists) kept |
| `skills` | + `embedding Vector(384)` (skill2vec vector), `aliases` refreshed from `skill_aliases` |
| `profile_skills` / `job_skills` | as-is (they are the plan's `user_skills` / `job_requirements`) + `profile_skills.source ENUM(manual,resume)` |
| `applications` | + `saved` status added to enum; + `resume_id` FK (version link) |
| `interactions` | as-is; `metadata` now carries `propensity` for exploration events |
| `companies` | + `industry`, `size` (for filters & family inference) |

### 5.2 New tables

| Table | Purpose (plan §) | Key columns |
|---|---|---|
| `resumes` | versioned resumes (16, 20) | `profile_id, file_path, uploaded_at, parse_status, extracted JSONB, evidence JSONB` |
| `education` | structured (16) | `profile_id, degree, field, institution, grad_year, is_primary` |
| `experience` | structured (16) | `profile_id, title, company, start/end, description, skills_used[]` |
| `projects` | structured + mapping (13, 16) | `profile_id, name, description, links[], detected_skills[]` |
| `certifications` | structured (16) | `profile_id, name, issuer, issued_at, expires_at, credential_url` |
| `job_families` | alt-career discovery (10) | `name, parent_id, core_skills[]` (seed: ~25 roles) |
| `skill_aliases` | canonicalization (4) | `alias, skill_id, confidence, source(LLM\|admin)` |
| `skill_edges` | skill graph (7, 8) | `from_skill, to_skill, edge_type(prereq\|transfer\|supersedes), weight, source, approved` |
| `recommendations` | persisted feed/audit (16) | `profile_id, job_id, snapshot JSONB(components+scores), strategy, model_version, served_at` |
| `skill_gaps` | gap snapshots & improvement tracking (2, 20) | `profile_id, job_id, classes JSONB, filled_at` — diffing two snapshots = "improvement" |
| `career_paths` / `career_path_steps` | roadmap (8, 16) | `profile_id, target_family_id, status` / `path_id, seq, kind(skill\|project\|cert), skill_id, est_hours, done_at` |
| `learning_resources` | roadmap (16) | `skill_id, title, url, kind, level, hours, quality_score` (seeded curated set; LLM may propose, admin approves) |
| `simulations` | what-if history (9) | `profile_id, mutation JSONB, result_delta JSONB, created_at` |
| `feedback` | feedback loop (19) | `profile_id, job_id, reason ENUM(relevant,not_relevant,already_applied,not_interested,too_difficult,location_issue,salary_issue,other), note, created_at` |
| `skill_affinities` | learned negative/positive leanings (19) | `profile_id, skill_id, score, updated_at, decay` (user-resettable) |
| `model_registry` | model ops (6) | `name, version, artifact_path, metrics JSONB, trained_at, active` |
| `llm_usage` | admin monitoring (21) | `route, prompt_hash, tokens_in/out, latency_ms, cached, cost_estimate` |
| `learning_resource` approvals, `system_config` | admin-tunable weights/thresholds (6, 21) | `key, value JSONB, updated_by` |

**Migration plan:** 6 Alembic revisions (see §23), all additive; JSONB snapshots keep old rows valid.

---

## 6. The Model Suite — real, trained artifacts

> This section is the answer to *"make a real model … not just something which already exists."*
> Four trainable artifacts are **trained by us, on our corpus**, versioned in `model_registry`,
> scored by the §21 harness. The LLM is **not** one of them — it labels and narrates; it never ranks.

### M0 — Embedder (backbone, off-the-shelf, swappable)
- **Model:** `sentence-transformers/all-MiniLM-L6-v2` (384-d — matches the existing `Vector(384)` columns), run locally in the API container. Config: `EMBEDDING_MODEL` (swap to `bge-base`/`e5` via env — plan §5 lists all three as candidates; we *choose one*, per plan).
- **Trains:** nothing by default. **Stretch (Phase 5):** contrastive fine-tune on (profile, job) pairs where the interaction label is positive (apply/save) vs. in-batch negatives — our own weights, same 384-d interface, registered as `embedder v1`.
- **Why real:** embeddings become first-class *today* (columns exist, unused); fine-tune gives a custom retrieval model once interactions accrue.

### M1 — `skill2vec`: skill representation & transfer model *(trained)*
- **Training data:** skill co-occurrence corpus from (a) existing `job_skills`, (b) **live job postings fetched via job APIs and snapshotted** (~1,500–2,500, §20), (c) curated skill lists. Window = one posting; min_count = 3.
- **Algorithm:** Skip-gram Word2Vec (gensim), dim = 64. Deterministic seed.
- **Artifact:** `backend/ml/artifacts/skill2vec_v*.joblib` + per-skill rows in `skills.embedding`.
- **What it powers:**
  1. **Transferable-skill detection** (plan §7): `transfer(u→j)` when cosine(u, j) ≥ τ_transfer (default **0.65**) *or* taxonomy sibling — the TensorFlow→PyTorch example is an explicit acceptance test.
  2. **Analogical structure** in skill graph edge proposals (`king-queen` style analogies used to propose `skill_edges`, admin-approved).
  3. Roadmap effort discounting (§9): relatedness of missing skill to possessed skills.
  4. Fallback for skill-name similarity when aliases are missing.

### M2 — `ranklet`: Learning-to-Rank ranker *(trained — the headline model)*
- **Type:** LightGBM **LambdaRank** (GDBT), regression on graded relevance. CPU-trainable, millisecond inference, native feature importances → feeds explanations.
- **Groups:** one group = one user's impression feed (needed by LambdaRank).
- **Features (~30, all deterministic & logged):** the 8 component scores (§7) + sub-signals (required/preferred skill coverage separately, missing-required count, semantic cosine raw, exp gap in years, education rank delta, salary IoU, location class, family match, job age, applicant_count, profile completeness, company/family historical apply rate, skill-affinity sum, exploration flag).
- **Labels (graded):** `view=1, click=2, save=4, apply=6, shortlisted=8, interview=9, offer=10, feedback.relevant=8, feedback.not_interested/too_difficult=0, dismiss=0`.
- **Training data:** Phase 3 bootstrap = **synthetic interactions** generated from a pluggable ground-truth function + the deterministic scores (sanity floor), then replaced incrementally by real `interactions`/`feedback`/`applications` rows. Propensities logged for IPS correction (§21).
- **Serving:** `services/rerank.py` loads active version at startup; `strategy` config: `deterministic` (default) → `ltr_blend` (α=0.35, contribution clamped ±15 pts) → `ltr_full` (only after eval gate). Always records `model_version` into `recommendations.snapshot`.
- **Why real:** trained on our labels, versioned, evaluated on NDCG/MRR (§21), degradable to pure-deterministic in one env var.

### M3 — `calibrator`: readiness calibration *(trained)*
- **Type:** **isotonic regression** mapping `ranklet` score (or, in `deterministic` strategy, the FinalScore) → empirical P(positive outcome). Fallback: Platt scaling if < 500 labels.
- **Powers:** the plan's **Job Readiness** number ("Readiness: High/Medium/Low", simulator percentages). Bands: ≥0.80 High, 0.60–0.79 Medium, <0.60 Low (config).
- **Why real:** turns "74%" from an arbitrary weighted sum into a *calibrated probability* — the difference between a demo score and a measured one.

### M4 — `preference-learner`: per-user utility weights *(trained, online)*
- Covered in §16 — a bounded, partial-pooling weight adaptation trained from that user's feedback with decay + reset.

### M5 (stretch) — Bradley-Terry cold-start elicitation
- 3 pairwise "which job would you prefer?" choices at onboarding → fit a Bradley-Terry model over the 8 component axes → initial user weight vector before any history exists. Optional Phase 5; deterministic fallback = global weights.

**Training orchestration:** `backend/ml/train.py --all` runs M1→M2→M3, writes metrics + artifact to `model_registry`, promotes only if eval gates pass (§21). Runs manually / via CI schedule; inference needs no GPU.

---

## 7. Deterministic Scoring Engine

> Plan §6 exact form: `FinalScore = Σ wᵢ·Componentᵢ`, weights configurable, **LLM never touches a score.**
> Every component ∈ [0, 100]; all inputs come from DB/config — no network calls inside scoring.

```
FinalScore = 0.30·SemanticSimilarity + 0.25·SkillMatch + 0.15·ExperienceMatch
           + 0.10·EducationMatch + 0.05·ProjectMatch + 0.05·LocationMatch
           + 0.05·SalaryMatch + 0.05·CareerInterestMatch          (Σw = 1.00)
```

| Component | Formula (defaults) |
|---|---|
| **SemanticSimilarity** | `100·clamp((cos(e_profile, e_job) − c_lo)/(c_hi − c_lo))`, c_lo=0.25, c_hi=0.75 (refit from data at eval time). `e_profile` = embed(headline + bio + canonical skills + target family + project blurb); `e_job` = embed(title×3 + requirements×2 + description + canonical required skills×3). |
| **SkillMatch** | Weighted coverage over `job_skills`: `Σ w_eff·credit(s) / Σ w_eff ×100`, `w_eff = importance·(1.6 if required else 1.0)`. `credit`: **strong** = 1.0 × prof_mult (beginner .7 / intermediate .9 / advanced-expert 1.0), **partial** = 0.6, **transferable** = 0.7 × min(1, cos_skill2vec), **missing** = 0. Cap 100. Job without skills → 80 (neutral, existing behavior). |
| **ExperienceMatch** | Existing `_compute_experience_fit` piecewise function **kept as-is** (in-band 100; under-experience −25/yr floor 20; overqualified −8/yr floor 60; no data → 70). |
| **EducationMatch** | Degree rank {none 0, diploma 1, bachelor 2, master 3, phd 4}. `rank_user ≥ rank_req` → 100; else `max(0, 100 − 25·gap)`; field mismatch when required → ×0.6. No requirement → 100. |
| **ProjectMatch** | Coverage of job's required+preferred skills by the union of user project skills (from `projects.detected_skills`), same credit function at 0.5 scale + domain-tag Jaccard/2. No projects → 40 (explicit low, surfaced as a *concern* + roadmap project step). |
| **LocationMatch** | remote job → 100; exact city → 100; same state/country → 80; user in `preferred_locations` → 100; else 40 (remote-open flag lifts to 70). |
| **SalaryMatch** | Normalize both sides via FX table → interval IoU: expected fully covered → 100; partial → `100·(overlap/expected_width)` floor 20; disjoint below → `max(0, 100 − 2·gap%)`; missing data → 70. |
| **CareerInterestMatch** | target family = job family → 100; graph distance 1 → 70; else Jaccard(interest skills, job skills)·100. |

**Worked example (plan §2 reproduced):**

| Comp | Value | ×w | | Comp | Value | ×w |
|---|---|---|---|---|---|---|
| Semantic | 70 | 21.00 | | Education | 100 | 10.00 |
| Skill | 68 | 17.00 | | Project | 50 | 2.50 |
| Experience | 85 | 12.75 | | Location | 80 | 4.00 |
| Salary | 60 | 3.00 | | Interest | 75 | 3.75 |
| | | | | **FinalScore** | | **74.0** ✓ |

→ **Current Match: 74%** → M3 calibration → **Readiness band** → components feed §12 explanation verbatim.

**Cold start** (no skills, no text): deterministic fallback = ExperienceMatch·0.5 floor 30 (existing behavior) until M5/elicitation; completeness score unchanged.

**Config precedence:** defaults (code) → `system_config` table (admin panel) → env override. Weights validated Σ=1 on save.

---

## 8. Skill taxonomy, normalization & Skill Gap Engine

### Normalization (plan §4)
Resolution order: exact canonical → `skill_aliases` (case-fold) → fuzzy (rapidfuzz ≥ 92) → skill2vec nearest with confidence ≥ 0.8 → **create new canonical** (flagged for admin review). All profile/job skill writes route through `normalize_skill()`; the current `ilike` upserts in `profiles.py`/`jobs.py` are replaced by it.

Seed aliases ship in-repo (`backend/ml/data/skill_aliases.yaml`): `Python 3 / Python Programming / Python Dev → Python`, `React.js / ReactJS / react → React`, `Node / NodeJS → Node.js`, … LLM may *propose* aliases in bulk; they enter with `source=LLM, confidence<1` until admin approval (plan §21 merge tool).

### Skill graph (`skill_edges`)
- `prereq`: curated seed (~150 edges, in-repo, reviewable: `SQL→PostgreSQL`, `Docker→Kubernetes`, `Python→FastAPI`…). Prereqs drive roadmap ordering.
- `transfer`: M1 cosine ≥ 0.65, auto, admin-curable.
- Admin merge (§22) rewrites edges transactionally.

### Gap Engine (plan §7) — `services/gap_engine.py`
Pure function `compare(profile, job) → SkillGap`:

```
per required/preferred job skill:
  STRONG        same canonical skill, (prof ≥ intermediate OR years ≥ 2)
  PARTIAL       same canonical skill, weaker evidence; OR alias/parent match
  TRANSFERABLE  no exact match, but skill2vec cos ≥ 0.65 (or graph sibling)
  MISSING       otherwise
+ missing_required[], weakest_link (highest-weight missing), gap_score (= SkillMatch)
```

Output feeds: recommendation card, `/jobs/{id}` detail, `skill_gaps` persistence, roadmap generation, simulator deltas. Classification thresholds live in config.

---

## 9. Career Roadmap Generator

**Deterministic spine (`services/roadmap.py`):**
1. Input: target job/family + `GapEngine` output.
2. Candidate set = `missing_required ∪ weak partials` (weak = beginner with importance ≥ 1.4).
3. **Order:** topological sort over `skill_edges.prereq`, ties broken by (a) skill2vec relatedness to possessed skills desc, (b) importance desc, (c) name — fully deterministic.
4. **Interleave steps:** after every 2 skill steps insert a `project` step (uses the missing skills; skipped if user already has a qualifying recent project) — mirrors plan §8's `Dockerize app` / `Build production backend` pattern; optionally a `cert` step for cloud skills.
5. **Effort model (deterministic):** `hours = base_hours[category] × difficulty_mult × (1 − 0.4·max_cos_to_possessed)`; base: language 80, framework 60, database 50, cloud 70, devops 70, ml 90, soft 30 (default 50); clamp [8, 120]. Bands: <30 Low effort, 30–70 Medium, >70 High.
6. Phase grouping: pack steps ≤ 25 h/phase → `Phase 1..n` with `est_hours` each; **"Estimated readiness after roadmap: {from_band → to_band}"** computed by re-running scoring with roadmap completion applied to a *shadow* profile (same mechanism as the simulator — one code path).

**LLM periphery:** renders phases as coach-style prose **with numbers passed through untouched** (prompt rule + post-validation: regex-extract every `\d+` from output, assert multiset equality with input — mismatch → discard LLM text, fall back to template).

**Respect existing proficiency (plan §8):** possessed-strong skills never appear as steps (assertion + test).

Persisted in `career_paths`/`career_path_steps`; `done_at` enables §19 "track improvement" (path completion % + gap snapshot diffs).

---

## 10. What-If Career Simulator

`services/simulator.py` — **counterfactual re-scoring, nothing more.**

```
POST /simulate
  mutation: { add_skills:[{name,level}], remove_skills:[],
              expected_salary?{min,max,currency}, location?,
              work_mode?, target_family?, add_project?{} , add_cert?{} }
→
  context' = apply_mutation(shadow_context(profile), mutation)   # in-memory only
  for job in candidate_jobs: recompute components (§7) with context'
  delta per job = (FinalScore' − FinalScore, band' vs band, newly_eligible/lost)
  + target-role readiness: band(context', target) and band-after-each-single-skill
  → persist simulations; NEVER touch profile_skills/profiles
```

- Guarantees: **idempotent** (same mutation twice → identical JSON — property test), **fast** (only score top-100 candidates, embeddings of profile recomputed in-memory with the same embedder), **honest** (band changes attributed to the specific component deltas: "Docker +7 SkillMatch → +1.75 FinalScore → Medium→High").
- API also returns `suggested_order`: per-skill readiness gain desc = which hypothetical helps most (this powers the plan's "After adding Docker: 69%, After AWS: 76%" list — computed, not invented).
- UI: skills chip-search (canonical names only), salary slider, location select; "Commit to profile" button is an explicit user action that copies the shadow skill into the real profile (then re-embeds).

---

## 11. Alternative Career Discovery

- Every job is assigned a `job_family_id` (seed ~25 families: Backend, Frontend, Full-Stack, Data Analyst, Data Engineer, ML Engineer, DevOps, SRE, PM, QA, Android, iOS, …). Assignment: title-pattern rules first (deterministic), LLM proposes only for unmatched titles (validated against the family enum).
- **Role affinity score** per family = weighted overlap of user skills (with transfer credit) vs. family core skills (median skill profile of that family's jobs) + semantic cosine(user, family centroid embedding) → [0,100].
- Discovery = families with score ≥ τ (default 55) **excluding** current target family, sorted desc; explanation = top-4 overlapping skills + "N of your skills transfer" + nearest family edge. Same math renders as **simulator presets**: "If you targeted {family}: readiness X%."
- No arbitrary suggestions: every listed family passes the overlap threshold — unit test asserts threshold enforcement.

---

## 12. Explainability layer

**Explanation contract** — built *by the engine*, per recommendation, stored in `recommendations.snapshot`:

```jsonc
{
  "final_score": 74.0, "readiness": {"value": 0.71, "band": "medium"},
  "strategy": "deterministic", "model_version": null,
  "components": [ {"name": "skill", "value": 68, "weight": 0.25, "contribution": 17.0}, ... ],
  "strengths": [                       // from engine rules
    {"kind": "skill", "text": "Strong Python proficiency (Advanced)"},
    {"kind": "skill", "text": "Matches 6 skills: Python, ML, SQL, Pandas, Scikit-learn, Git"},
    {"kind": "project", "text": "Relevant project experience: Solar PV System (Full-Stack)"},
    {"kind": "location", "text": "Location preference matches"}],
  "concerns": [
    {"kind": "missing_required", "skills": ["PyTorch","Docker","AWS"],
     "text": "Missing required: PyTorch, Docker, AWS"},
    {"kind": "project_gap", "text": "No deployment project demonstrated"}],
  "recommended_action": {"text": "Build and deploy one containerized REST API project",
                          "path_id": "..."},
  "delta_note": "Model adjusted +6.0 (driven by: company affinity, past saves)" // only in blend mode
}
```

- **UI maps 1:1 to plan §11:** *Why this job appears* ← `strengths`; *Potential concerns* ← `concerns`; *Skill gap* ← gap engine; *Recommended action* ← roadmap step 1.
- Optional **LLM polish** (`EXPLAIN_LLM=true`): rewrites `strengths`/`concerns` into flowing sentences **given the fixed JSON as source**; validator: every skill/number mentioned must appear in the source JSON (hallucinated tokens → discard). Default off for cost; templates are already human-readable.
- In blend mode the UI shows deterministic components *plus* the bounded `delta_note` with top-3 `ranklet` feature importances — the model's influence is visible and attributable, never a black box.

---

## 13. Resume Improvement Engine

`POST /jobs/{id}/resume-optimize` → inputs: resume `evidence` JSON + JD extraction + gap output.

**Deterministic layer:**
- Missing keywords: canonical JD required terms absent from resume tokens (normalized) → `missing_keywords[]`.
- Missing skills / weak evidence: gap engine + evidence count per skill (0 mentions → "not demonstrated").
- ATS checks (rules): section presence (summary/experience/projects/skills), length bounds, keyword coverage %, quantified-bullet %, contact block completeness → each PASS/WARN/FAIL.

**LLM layer (grounded):** critique of *existing* project/experience bullets vs. JD (re-ordering, quantification, terminology), suggested rewrites **cited to the original bullet span**.

**Anti-fabrication contract (plan §12):**
1. Output schema marks each proposed item `existing | rewrite_of(span)`.
2. **Validator:** any skill token in the LLM output must ∈ (resume evidence ∪ JD-required-missing-list explicitly labeled "gap — do not claim"). Violation → item dropped + `llm_usage.flagged++`.
3. UI copy: *"We will never add a skill you haven't demonstrated. Missing skills stay missing — here's the roadmap instead."*

---

## 14. Project-to-Job Mapping

- Projects' `detected_skills` are produced at creation time: LLM extraction over project description (evidence spans, same validator as resume) → canonicalized.
- `project_relevance(project, job) = Σ credit over job skills using project skills (required ×1.6)` → banded: ≥70 Very high, 50–69 High, 35–49 Moderate, <35 Low (thresholds config; plan §13 example classes map exactly).
- Surfaced in two places: on the job card ("Powered by: Solar PV System — Very high") and on the profile ("This project benefits: Full-Stack Developer (Very high), Backend (High) …") — plan §13 both directions.

---

## 15. LLM Layer — providers, prompts, safety

**Provider abstraction (`app/services/llm/provider.py`):**
```python
class LLMProvider(Protocol):
    def complete_json(self, schema: type[BaseModel], prompt: str,
                      *, system: str, max_tokens: int) -> tuple[BaseModel, LlmUsage]
```
- `OpenAIProvider` (**default**; `OPENAI_API_KEY`, model via `LLM_MODEL`, e.g. `gpt-4o-mini` for extraction routes / stronger model for roadmap prose), `GeminiProvider` (retained adapter), `OpenAICompatProvider` (custom `base_url` — covers local Llama via Ollama, etc.). Selection: `LLM_PROVIDER` env.
- **Retry:** schema-validation failure → 1 repair turn with validator errors pasted → regex-fence cleanup (existing pattern) → **graceful degrade** per feature (regex parser / templates) — no user-facing 500 ever.
- **Cache:** `sha256(prompt)` → in-DB or in-process TTL cache; job-extraction and roadmap-prose are high-hit-rate.
- **Log:** every call → `llm_usage` (route, tokens, latency, cost estimate, cache hit, flagged) → admin dashboard (plan §21).

**Prompt inventory (all in `app/services/llm/prompts.py`, all Pydantic-schema'd):**

| # | Prompt | Schema | Fallback |
|---|---|---|---|
| P1 | Resume → structured (exists, **upgraded**: + evidence spans, + projects, + certifications, + interests) | `ParsedResume` | regex parser (exists) |
| P2 | JD → structured (title, skills required/preferred w/ importance, exp/edu reqs, industry, seniority) | `ParsedJob` | regex + skill keyword scan |
| P3 | Raw skill strings → canonical candidates + proposed aliases | `SkillProposal[]` | skip (admin manual) |
| P4 | Unmatched job title → family (validated against family enum) | `{family}` | `other` bucket |
| P5 | Roadmap numbers → coach prose (digit-preservation validator) | `{sections}` | deterministic template |
| P6 | Explanation polish (optional) | `{sentences}` | engine templates |
| P7 | NL query → `SearchFilters` (whitelisted fields/enums only) | `SearchFilters` | treat as FTS text |
| P8 | Project text → skills + evidence | `ProjectSkills` | keyword scan |
| P9 | Bullet critique for resume optimizer | `BulletRewrite[]` | ATS report only |
| P10 | Skill prerequisite edge proposals → `skill_edges(source=LLM, approved=false)` | `EdgeProposal[]` | curated seed only |

**Safety rails (plan §18, one per "must not"):**

| Forbidden | Enforcement |
|---|---|
| Invent user skills | P1/P8 evidence-span validator (span must appear in source text) |
| Invent experience/certifications | same validator + `unverified` marking |
| Invent job requirements | P2 output limited to skills present in JD text (span check) or existing taxonomy; `confidence` field |
| Assign scores | scoring/rerank/calibration modules take **no LLM input** (import-boundary; lint rule) |
| Execute SQL | P7 returns JSON filters → validated → existing typed query builder (§17) |
| Auto-apply | no LLM tool has any write path to `applications` (only user POST does) |
| Zustand/Zod note | Pydantic is the single source of truth; TS types generated/duplicated in `lib/types.ts` |

---

## 16. Feedback Loop & Personalization Model

**Capture (plan §19):** `POST /feedback` with the 7 reasons + free note; plus existing `interactions` (view/save/apply/dismiss). Job card → "Not relevant ▾" reason menu.

**M4 `preference-learner` (trained, online, bounded):**
- State: user weight vector `w_u` over the 8 components (init = global config), + `skill_affinities` (per-skill lean, init 0).
- Update (on each feedback/interaction batch, async job):
  - Component weights: multiplicative update toward the *component value of the liked item* vs. *disliked item* (if liked item scored high on location and was rejected for salary → salary weight ↓, location ↑), lr η=0.15, **bounds [0.5·w_global, 2.0·w_global]**, renormalized Σ=1.
  - Skill affinities: `too_difficult/not_interested` on Java-heavy jobs → `affinity(Java) += −0.25`; `relevant/apply` → `+0.2`; clamp [−1, 1], half-life decay 30 days; applied as `SkillMatch` penalty `max(0, 1 + affinity·0.3)` — **never full removal** (plan: "should not blindly remove roles").
- **Exposure:** Settings → "Your preferences" shows current 8 weights as bars + recent learned changes; **Reset to defaults** button (deletes `w_u` + `skill_affinities`). In recommendations response: `personalization_note: "Salary weight raised to 0.09 because of your recent feedback"`.
- Cold users: partial pooling — shrinkage factor `n/(n+k)`, k=10 → new users ≈ global weights (this *is* the model: an empirical-Bayes update, not a prompt).

---

## 17. Search: structured + NL + hybrid retrieval

**Structured:** extend existing `/jobs` (FTS + GIN + filters — already solid) with: `company`, `industry`, `family`, `required_skill` multi, `work_mode`, `page` — plan §15 filter list completed.

**NL (plan §15 example query):** `GET /jobs/nl?q=...` → P7 → `SearchFilters` (Pydantic: enums validated, `skills` canonicalized, `min_salary` int-coerced, unknown fields dropped) → **same query builder** → results + `parsed_filters` echoed so the UI shows chips the user can edit (user, not LLM, is the final authority).

**Hybrid ranking** when relevance sort + query present: `RRF(k=60)` over (a) `ts_rank_cd` order, (b) pgvector KNN order on `e_job`, (c) skill-set match count — replaces single-metric sort. Deterministic tie-break: recency, then `job.id`.

---

## 18. API surface

All under `/api/v1`, JWT via existing `deps.py`; roles: public / seeker / employer / admin.

| Method & path | Purpose |
|---|---|
| `GET /recommendations?limit&strategy` | Feed (§4 flow A) — response = plan §14 card data + explanation contract |
| `GET /recommendations/{job_id}/gap` | Skill Gap detail (§8) |
| `GET /recommendations/{job_id}/roadmap` | Roadmap for this job (§9), creates `career_paths` row |
| `POST /roadmaps/{id}/steps/{sid}/complete` | Mark step done → re-evaluate bands |
| `GET /careers/discover` | Alternative families (§11) |
| `POST /simulate` / `GET /simulations` | What-if (§10) |
| `POST /feedback` | §16 |
| `GET/PATCH /preferences` | read/reset learned weights (§16) |
| `POST /jobs/{id}/resume-optimize` | §13 |
| `GET /jobs/nl?q=` | §17 |
| `GET /jobs/{id}/project-map` | §14 |
| `GET /applications` + `PATCH /applications/{id}` | tracker (statuses incl. `saved`) |
| `GET /applications/stats` | analytics: counts + *"skills in your successful applications: … (historical observation)"* |
| `POST/GET /profiles/me/resume` (exists) + `GET /profiles/me/resumes` | versions |
| Education/experience/projects/certifications CRUD | `PUT /profiles/me` extended or sub-routers |
| `GET /search/skills?q=` | autocomplete through normalizer |
| **Admin:** `GET/POST/PATCH /admin/skills` (merge!), `GET /admin/jobs/duplicates`, `GET /admin/llm-usage`, `GET /admin/parse-failures` (+retry), `GET/PUT /admin/config` (weights), `GET /admin/models` (registry) | plan §21 |

`recommendations` response schema: existing `RecommendationItem` **extended** (keeps current frontend compiling): + `readiness`, + `explanation` (contract), + `family`, + `job.project_relevance`, + `personalization_note`, + `strategy/model_version`.

---

## 19. Frontend plan

Stack unchanged (Next.js App Router, Tailwind, lucide — matches `frontend/AGENTS.md`; **read `node_modules/next/dist/docs/` guides before writing Next code**).

| Route | Content (plan §22) | Notes |
|---|---|---|
| `/` | Landing | exists — refresh copy to "career decision-support" positioning |
| `/login`, `/register` | auth | exists |
| `/onboarding` | *(new, optional M5)* 3 pairwise choices + target family | skip-able |
| `/resume` | upload, parse status, **evidence review** (per-skill verify/ignore toggles) | extends profile page |
| `/profile` | builder: skills(proficiency), education, experience, projects, certs, salary expectation, preferred locations/mode, **career interests & target role** | extends existing |
| `/dashboard` | completeness %, readiness overview, top matches (§14 card), gap summary strip, path progress, tracker stats | new |
| `/recommendations` | existing feed **+ readiness band, explanation sections, feedback menu, diversity-varied list** | extend in place |
| `/jobs`, `/jobs/[id]` | search(+NL bar+filter chips), detail **+ Gap panel + Project relevance + Resume-optimize CTA** | extend |
| `/gap/[jobId]` | strong/partial/transfer/missing columns + "path to ready" | new |
| `/roadmap` | target selector, phase timeline, est. hours, complete toggles, readiness-after | new |
| `/simulator` | mutation form → delta table (Δscore, band flips) → "commit to profile" | new |
| `/resume-optimize` | per-job ATS report + grounded suggestions | new |
| `/saved`, `/tracker` | saved jobs; application pipeline + analytics | new (`saved` status) |
| `/settings` | preferences bars + reset, account | new |
| `/admin` | skills merge, duplicates, LLM usage, parse failures, config weights, model registry | new, role-gated |

Design system: keep the existing zinc/teal dashboard language (already established in `recommendations/page.tsx`) — hierarchy first, AI text second (plan §22).

---

## 20. Pipelines & batch jobs

| Job | Trigger | Steps |
|---|---|---|
| `scripts/embed_backfill.py` | after migrations; on-demand | embed all jobs/profiles/skills → write `embedding` + `embedding_updated_at` |
| `scripts/fetch_jobs_live.py` | once (+ weekly refresh) | **Live-first corpus:** pull real postings from job APIs (primary: **Adzuna** — India + 15 other countries, free key, salary/location fields; secondary: Arbeitnow / Remotive / Jobicy for remote roles) → normalize to our schema → **P2 LLM extraction** populates structured `job_skills` (required + importance) → upsert into `jobs` with `source`/`external_id`/`external_url` → **snapshot** the fetched set to `ml/data/corpus-YYYYMMDD.jsonl` as the frozen train/eval corpus. Apply on external jobs opens `external_url`; view/save/click interactions on them are logged and train M2 normally. Attribution (`source` + apply link) satisfies API ToS. |
| `scripts/synthesize_corpus.py` | as needed | **Fixtures only (demoted):** ~100 crafted golden postings — edge cases (missing salary, mixed required/preferred, ambiguous titles) for eval sets; skill2vec backfill if the live fetch is short; offline fallback when no API key is present. |
| `ml/train.py --all` | manual / weekly CI | M1 → build datasets → M2 → M3; register/promote on gate pass |
| `services/embeddings.invalidate` | on profile/job/skills write | set `embedding=NULL` → lazy re-embed on next read + sweep task |
| `scripts/seed_canonical.py` | once | aliases, prereq edges, families, resources, FX rates (extends existing `seed_skills.py`) |

Profile parse flow (existing background task) extended: P1 → validators → **all structured tables** → alias resolution → embedding backfill — one orchestrated `_run_resume_parse` (modified file).

### 20.1 Ingestion & preprocessing pipeline (live data)

Raw API data is messy — this pipeline is **mandatory, not optional**. Seven idempotent stages (re-runs are safe; every stage is a pure transform + upsert):

| Stage | Module | What happens |
|---|---|---|
| **0. Land** | `ingest/fetch.py` | Provider interface — Adzuna primary (India+global, free key), Arbeitnow/Remotive/Jobicy adapters — → immutable raw landing file `ml/data/raw/{source}-{date}.jsonl`. Rate-limited, checkpointed, resumes where it stopped. **Never runs in a request path.** |
| **1. Clean** | `ingest/clean.py` | HTML → text (strip tags, decode entities, kill `<br>`/&amp; soup), Unicode NFKC, whitespace collapse, boilerplate removal (EEO/apply-identical blocks) → feeds existing `_clean_text` conventions |
| **2. Parse** | `ingest/parse.py` | `location` string → structured `{city, region, country}` (raw kept); employment type & seniority → existing enums (reuse `_SENIORITY_MAP`); salary → integer min/max/currency (FX-normalized at scoring time via `fx_rates`); experience text → years or NULL |
| **3. Structure** | P2 + `skill_normalizer` | LLM extracts required/preferred skills + importance → alias resolution → `job_skills`. LLM off → deterministic keyword-scan fallback (same tiering as the resume parser) |
| **4. Validate & gate** | `ingest/validate.py` | Quality gates: title non-empty · description ≥ 100 chars · ≥1 canonical skill (else flagged) · family assigned · `salary_min ≤ salary_max`. **Dedupe:** `(source, external_id)` unique + cross-source fuzzy dup (normalized title + company ≥ 0.92 → skipped, surfaced in admin duplicate panel) |
| **5. Embed** | `embeddings.ensure_job_embedding` | 384-d vector + refresh `search_vector` (existing FTS mechanism) |
| **6. Snapshot** | end of run | `ml/data/corpus-YYYYMMDD.jsonl` frozen for train/eval + **run report**: counts per stage, % missing salary, alias hit-rate, skill-coverage, skipped-dup count |

**Missing-value policy** — *never fabricate a displayed value; score with an explicit neutral prior and label the gap in the UI* (same anti-fabrication philosophy as the resume engine):

| Field | Frequency on live data | UI shows | Scoring uses (§7) |
|---|---|---|---|
| salary | often absent | "Not disclosed" | `SalaryMatch` = 70 neutral |
| experience req | vague phrasing | "Unspecified" badge | seniority/title regex inference → else 70 neutral |
| education req | frequently absent | hidden entirely | `EducationMatch` = 100 (no stated bar = no penalty) |
| skills | thin descriptions | "Not specified" | P2/keyword extraction; genuinely empty → neutral 80 |
| location | APIs always provide | — | fetch-gate: skip posting if absent |
| remote flag | varies by source | — | infer from `remote` field or description keyword → else False |

**Synthetic user/interaction bootstrap (confirmed):** `scripts/seed_synthetic_users.py` generates ~200 synthetic seekers (profile archetypes sampled from the golden resume set) with graded interactions (view/save/apply/dismiss) from a **pluggable ground-truth preference function** over the frozen corpus → written as *real* rows in `users/profiles/interactions` with **`metadata.synthetic=true`** (excluded from online metrics, deletable in one statement, gradually replaced by real behavior). This is the standing data for training `ranklet` (M2) and initial calibrator (M3) until real users arrive.

**Source policy:** LinkedIn has **no public job API** (partner-program only) and scraping it violates ToS → excluded. JSearch/RapidAPI is a possible *paid* extra later (Google-for-Jobs aggregate; free tier too small, ToS = read carefully) — not in base scope. Attribution for Adzuna/Remotive etc. handled via `source` column + apply link.

---

## 21. Evaluation plan

> Plan §24 verbatim, made executable. **Nothing ships on vibes.**

**Harness:** `backend/ml/evaluate.py` + `backend/tests/test_eval_regression.py` (gates in CI).

| Target | Metrics | Data | Gate |
|---|---|---|---|
| Ranker (M2) & full pipeline | **Precision@K, Recall@K, NDCG@K, MRR** (K=5,10,20) | held-out synthetic + real interactions (temporal split: train < t, test ≥ t) | blend strategy ships only if NDCG@10 ≥ deterministic baseline − 0 |
| Baselines compared | popularity, pure-deterministic, M2 | same split | report table in `model_registry.metrics` |
| Skill extraction (P1) | **precision/recall/F1** vs. hand-labeled golden set (~50 resumes in `ml/data/golden/`) | golden set | F1 ≥ 0.85 else prompt iteration |
| Resume parsing | field-level accuracy (degree/year/title) | same golden set | ≥ 0.80 |
| Semantic search | **Recall@K** of known-relevant pairs | synthetic relevance pairs | Recall@20 ≥ 0.75 |
| Transfer classification (M1) | P/R/F1 on labeled transfer pairs (golden ~200) | hand-labeled | F1 ≥ 0.80 |
| Calibration (M3) | Brier score, ECE | held-out outcomes | ECE ≤ 0.10 |
| Determinism | property tests: same input → identical score; Σw=1; simulator idempotence | unit | CI |
| **Online (plan §24)** | Relevant-rate, CTR (view→click), save rate, apply rate, dismissal rate; exploration slot measured with **IPS** using logged propensities | `interactions`/`feedback` | dashboards (admin), weekly review |

Explicit anti-pattern (plan §24): **no metric sourced from "LLM says it looks good."** LLM outputs are evaluated only via validators (schema pass rate, evidence-span pass rate — both logged).

---

## 22. Security, safety & ops

- **Auth:** existing JWT + roles; admin routes behind `require_roles(ADMIN)`; resume files served only to owner (fix current `?file=` download to check `profile_id` prefix ownership — known gap, patched in Phase 1).
- **PII:** resumes never leave the server; LLM calls receive resume text only when `LLM_PROVIDER` enabled — documented in privacy note; regex path available for no-key deployments.
- **LLM abuse containment:** timeouts (10 s), per-route token budgets, cache-first, cost meter on admin dashboard, kill switch `LLM_ENABLED=false` degrades every route to deterministic/template.
- **Rate limiting:** slowapi or reverse-proxy on auth + simulate + resume-optimize.
- **Observability:** structured logs, existing heartbeat health, `/admin/llm-usage`, recommendation latency histogram (log line per feed: candidate count, strategy, model_version, ms).
- **Data integrity:** all multi-entity updates in transactions (esp. skill merge), JSONB snapshots immutable (audit), FK cascades already consistent.

---

## 23. File-by-file implementation plan

> 🟩 = new file, 🟨 = modified file, ⬜ = untouched. Paths relative to repo root.

### Phase 1 — Foundations (schema, embeddings, normalization, scoring core)

| File | Action | Contents |
|---|---|---|
| `backend/alembic/versions/0006_profile_prefs_and_families.py` | 🟩 | profiles salary/interests/target/work-mode; companies.industry; jobs.family_id; applications `saved` + resume_id |
| `backend/alembic/versions/0007_structured_profile_tables.py` | 🟩 | resumes, education, experience, projects, certifications |
| `backend/alembic/versions/0008_skill_graph.py` | 🟩 | skill_aliases, skill_edges, skills.embedding, job_families |
| `backend/alembic/versions/0009_rec_and_feedback.py` | 🟩 | recommendations, skill_gaps, feedback, skill_affinities, simulations |
| `backend/alembic/versions/0010_paths_and_resources.py` | 🟩 | career_paths, career_path_steps, learning_resources |
| `backend/alembic/versions/0011_ops.py` | 🟩 | model_registry, llm_usage, system_config |
| `backend/app/models/*.py` (9 new model files mirroring above) | 🟩 | one file per domain, existing style |
| `backend/app/models/profile.py`, `job.py`, `skill.py`, `application.py`, `company.py` | 🟨 | new columns/enums |
| `backend/app/services/embeddings.py` | 🟩 | lazy singleton embedder, `embed_text(s)`, `ensure_profile_embedding`, `ensure_job_embedding`, batch backfill helpers, FX-normalize helper |
| `backend/app/services/skill_normalizer.py` | 🟩 | resolution pipeline, `normalize_skill()`, alias proposals ingest |
| `backend/app/services/skill_graph.py` | 🟩 | edges load, `transfer_confidence()`, `relatedness()`, topo sort, family affinity |
| `backend/app/services/scoring.py` | 🟩 | `ComponentInputs`, the 8 component functions, `score_pair()`, weight loading/validation — **pure, no I/O** |
| `backend/app/services/rerank.py` | 🟩 | strategy dispatch (`deterministic`/`ltr_blend`), model load, clamp logic (no-op until M2 ships) |
| `backend/app/services/recommender.py` | 🟨 | rewrite: candidate generation (KNN∪FTS∪skill RRF) → `scoring.score_pair` → blend → MMR+exploration → explanation contract; keep public `recommend_jobs` signature + cold-start behavior |
| `backend/app/services/explanation.py` | 🟩 | build/validate explanation contract (§12) |
| `backend/app/services/mmr.py` | 🟩 | MMR + family caps + exploration slot w/ propensity |
| `backend/ml/data/skill_aliases.yaml`, `skill_prereqs.yaml`, `families.yaml`, `fx_rates.yaml` | 🟩 | curated seeds |
| `backend/scripts/embed_backfill.py`, `seed_canonical.py` | 🟩 | batch |
| `backend/app/api/recommendations.py` | 🟨 | gap/roadmap sub-routes, extended response |
| `backend/app/api/profiles.py` | 🟨 | structured sub-resources, normalizer use, ownership check on resume download, extended parse task |
| `backend/app/api/jobs.py` | 🟨 | new filters (company/industry/family/skills[]), normalizer use |
| `backend/app/schemas/recommendation.py`, `profile.py`, `job.py` | 🟨 | extended models (additive) |
| `backend/tests/test_scoring.py`, `test_normalizer.py`, `test_explanation.py`, `test_mmr.py` | 🟩 | golden vectors: fixed profile+job → exact component tuple (plan §2 example = test case) |
| `backend/requirements.txt` | 🟨 | + `sentence-transformers`, `gensim`, `lightgbm`, `joblib`, `rapidfuzz`, `scipy` |

### Phase 2 — Gap, Roadmap, Simulator, Discovery (the differentiator UX)

| File | Action | Contents |
|---|---|---|
| `backend/app/services/gap_engine.py` | 🟩 | §8 four-class compare |
| `backend/app/services/roadmap.py` | 🟩 | §9 topological steps, effort model, phases, readiness-after via shadow scoring |
| `backend/app/services/simulator.py` | 🟩 | §10 mutation→shadow context→deltas, idempotent |
| `backend/app/services/career_discovery.py` | 🟩 | §11 family affinity + explanations |
| `backend/app/services/llm/provider.py`, `prompts.py`, `validators.py` | 🟩 | §15 abstraction, P1–P10, evidence/digit validators, cache, usage log |
| `backend/app/services/resume_parser.py` | 🟨 | route through provider abstraction; P1 upgraded schema with evidence; keep regex fallback |
| `backend/app/api/gap.py`, `roadmap.py`, `simulate.py`, `careers.py` | 🟩 | §18 routes |
| `backend/app/main.py` | 🟨 | register routers |
| `backend/tests/test_gap_engine.py`, `test_roadmap.py`, `test_simulator.py`, `test_discovery.py`, `test_llm_validators.py` | 🟩 | transfer example (TensorFlow→PyTorch), proficiency-not-in-roadmap, simulator idempotence, digit-preservation, family threshold |
| `frontend/src/app/gap/[jobId]/page.tsx`, `roadmap/page.tsx`, `simulator/page.tsx`, `careers/page.tsx` | 🟩 | §19 |
| `frontend/src/components/explanation-card.tsx`, `gap-columns.tsx`, `phase-timeline.tsx`, `delta-table.tsx` | 🟩 | shared UI |
| `frontend/src/lib/api.ts`, `types.ts` | 🟨 | new endpoints + types (zod optional at boundary) |

### Phase 3 — The trained models (M1–M3) + evaluation

| File | Action | Contents |
|---|---|---|
| `backend/app/services/ingest/` (`fetch.py`, `clean.py`, `parse.py`, `validate.py`) + `backend/scripts/fetch_jobs_live.py` | 🟩 | 7-stage live ingestion pipeline (§20.1): Adzuna provider → clean → parse → P2 structure → gates/dedupe → embed → snapshot + run report |
| `backend/scripts/synthesize_corpus.py` | 🟩 | golden fixtures only — ~100 edge-case postings (missing salary, mixed required/preferred, ambiguous titles) (§20) |
| `backend/scripts/seed_synthetic_users.py` | 🟩 | ~200 synthetic seekers + graded interactions, `metadata.synthetic=true` (§20.1) — standing training data for M2/M3 |
| `backend/ml/train_skill2vec.py` | 🟩 | M1 |
| `backend/ml/build_datasets.py` | 🟩 | interactions/feedback/funnel → graded labels, groups, temporal split, synthetic bootstrap generator |
| `backend/ml/train_ranklet.py` | 🟩 | M2 LightGBM LambdaRank + feature manifest (names written into artifact) |
| `backend/ml/calibrate.py` | 🟩 | M3 isotonic/Platt |
| `backend/ml/train.py` | 🟩 | orchestrate + register/promote gates |
| `backend/ml/evaluate.py` | 🟩 | §21 metrics suite (P@K/R@K/NDCG/MRR/Brier/ECE/F1) + baseline table |
| `backend/ml/data/golden/*` | 🟩 | ~50 labeled resumes, ~200 transfer pairs, relevance pairs |
| `backend/app/services/rerank.py` | 🟨 | real inference (was stub), feature build from `ComponentInputs`+context |
| `backend/tests/test_eval_regression.py` | 🟩 | CI gates |
| `frontend` | 🟨 | show `strategy/model_version/delta_note` in feed (flag-driven) |

### Phase 4 — Feedback, tracking, search, resume optimizer, projects

| File | Action | Contents |
|---|---|---|
| `backend/app/services/personalization.py` | 🟩 | M4 weight update, affinities, decay, reset |
| `backend/app/api/feedback.py`, `preferences.py` | 🟩 | §18 |
| `backend/app/services/nl_search.py` | 🟩 | P7 → filters → query builder; hybrid RRF re-rank in `jobs.py` |
| `backend/app/services/resume_improve.py` | 🟩 | §13 two layers + anti-fabrication validator |
| `backend/app/services/project_mapping.py` | 🟩 | §14 |
| `backend/app/api/applications.py` (both files) | 🟨 | `saved` status, stats incl. skill-observation line |
| `backend/app/api/jobs.py` | 🟨 | `/jobs/nl`, RRF sort |
| `backend/tests/test_personalization.py`, `test_nl_search.py`, `test_resume_improve.py`, `test_project_mapping.py` | 🟩 | bounds/reset, filter whitelist rejection, fabrication rejection |
| `frontend`: `dashboard`, `tracker`, `saved`, `settings`, `resume-optimize`, feedback menu | 🟩/🟨 | §19 |

### Phase 5 — Admin, M5, polish

| File | Action | Contents |
|---|---|---|
| `backend/app/api/admin.py` | 🟩 | skill merge (transactional rewrite), dup-job detection (cos ≥ .92 + title sim), llm-usage, parse-failures+retry, config weights, model registry |
| `backend/app/services/elicitation.py` + `/onboarding` | 🟩 | M5 Bradley-Terry (optional) |
| `backend/app/services/explanation.py` | 🟨 | LLM polish flag (P6) |
| `frontend/src/app/admin/*` | 🟩 | role-gated panels |
| `README.md` | 🟨 | architecture + eval instructions |

**Approximate effort (1–2 devs):** P1 ≈ 4 d · P2 ≈ 4 d · P3 ≈ 4–5 d · P4 ≈ 4 d · P5 ≈ 2 d → **~18–19 dev-days**.

---

## 24. Milestones, scope & demo script

| Milestone | Gate to call it done |
|---|---|
| **M1 Foundations** | feed scores recomputed by `scoring.py` with golden tests green; embeddings backfilled; aliases resolve `React.js=React`; resume download ownership fixed |
| **M2 Differentiators** | plan §2 example reproducible end-to-end (74% card → gap columns → roadmap with hours → simulator +7% for Docker); all P2 tests green |
| **M3 Real models** | `model_registry` has skill2vec+ranklet+isotonic with metrics; eval report: ranker ≥ deterministic baseline on NDCG@10; strategy flag switches live |
| **M4 Loop** | feedback → weight change visible in settings → feed re-rank; NL query demo; resume-optimize with validator; tracker analytics |
| **M5 Ops** | admin merge demo; LLM kill-switch proven; docs updated |

**MoSCoW cut lines (if time-boxed):** Could-have = M5 elicitation, LLM explanation polish, contrastive embedder fine-tune, dup-job auto-merge (detection alone ships). Must-not-cut = §7 engine, §8 gap, §9 roadmap, §10 simulator, M2+M3 training pipeline, §21 harness — these *are* the project.

**Demo script (= plan §23 acceptance test):**
1. Upload `resume.pdf` → watch parse → evidence review shows spans.
2. Set target role "AI/ML Engineer" → feed: A 86 / B 81 / C 77 (numbers now *computed + calibrated*).
3. Open Job A → Gap columns: strong/partial/transfer/missing exactly as plan §23 → explanation sections.
4. Roadmap: Python/ML → PyTorch → Project → FastAPI → Docker → AWS → "readiness High".
5. Simulator: +Docker → watch 74→81 band flip; **commit** → real profile updates.
6. Feedback "Too difficult" on a Java job → settings shows Java affinity −0.25 → reset button restores.
7. NL search: *"entry-level backend jobs in Pune requiring Python and PostgreSQL, remote or hybrid"* → filter chips → results.
8. Admin: merge `Node`/`NodeJS` → all profiles/jobs re-pointed, embeddings refreshed.

---

## 25. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Interaction data too sparse for M2 | synthetic bootstrap + temporal eval + **strategy flag** (deterministic default is fully shippable); M2 improves as real data accrues |
| LLM cost/latency during demo | cache-first, `LLM_ENABLED` kill switch, templates already good, batch corpus gen off critical path |
| No LLM key/quota at eval time, or job API downtime/rate limit | every LLM route degrades to deterministic/template; corpus is **snapshotted on fetch day** into `ml/data/` + DB — demo and training never depend on live third parties; synthesis remains as final fallback |
| Scope creep (14 pages + 4 models) | MoSCoW cut lines §24; phases are independently demoable |
| Skill graph quality | curated in-repo seeds (reviewable YAML) + admin approval for LLM-proposed edges |
| Score↔model divergence confusing users | clamp ±15, always show deterministic components, `delta_note` explains model influence |
| Embedder downloads (~90 MB) in Docker build | pre-bake into backend image; CPU inference only; pin version |
| Simulator slow at scale | score only top-100 candidates; in-memory embeddings; p95 budget 500 ms (log it) |

---

## 26. Decisions log & open questions

**Decided (v1.1–v1.2):**
1. ✅ **LLM = OpenAI API key** — `OpenAIProvider` default; Gemini adapter retained (D3).
2. ✅ **Timeline & team size accepted** — full §23 scope (~18–19 dev-days) with MoSCoW cut lines as written.
3. ✅ **Corpus = live-first** — real postings fetched from a job API, LLM-structured, snapshotted for eval; synthesis demoted to eval fixtures + offline fallback (§20).
4. ✅ **Stack = Next.js + FastAPI** — D1 confirmed.
5. ✅ **Primary job API = Adzuna** (free key, India + global) with Arbeitnow/Remotive/Jobicy as remote supplement; behind a provider interface so swapping = one file. LinkedIn excluded (no public API / ToS); JSearch not in base scope (§20.1).
6. ✅ **Synthetic user + interaction data** = the model-bootstrapping dataset (`seed_synthetic_users.py`, flagged `metadata.synthetic=true`) until real behavior replaces it (§20.1).
7. ✅ **Preprocessing pipeline promoted to first-class** — 7-stage ingestion with quality gates + explicit missing-value policy (§20.1).

**Open:**
- **M5 onboarding elicitation** — in-scope or stretch? (Explanation provided in review; default = Phase 5 stretch, deterministic global weights until then.)

---

*Decisions log above = approval of this document (v1.1) → Phase 1 (§23) may begin.*
