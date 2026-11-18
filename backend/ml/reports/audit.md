# Phase 0 — Audit (no feature changes)

> **Status:** COMPLETE — awaiting owner approval of the cut list before Phase 1.
> **Data policy:** This audit used only **real** inputs: 10 anonymised real resumes (CC0-1.0, `opensporks/resumes`) and 1,117 real jobs (991 Adzuna + 120 Jobicy + 6 native). No synthetic profiles, synthetic interactions or formula-derived labels were used. See [`../DATA.md`](../DATA.md).
> **Generated:** 2026-11-19. Evidence file: `ml/reports/audit_feature_runs.json` (120 recorded runs).

---

## 1. What was read first (read-before-work requirement)

`README.md`; `docs/DESIGN.md` (all 779 lines); `docs/PROJECT_STATE.md`; `backend/ml/reports/master_project_evaluation.json` (all 789 lines); M0–M5 scripts: `train_biencoder.py`, `train_cross_encoder.py`, `build_embedding_pairs.py`, `eval_embeddings.py`, `train_skill_graph_gnn.py`, `train_skill2vec.py`, `build_datasets.py`, `train_neural_ranker.py`, `train_ranklet.py`, `train_score_weights.py`, `calibrate.py`, `train_bandit.py`, `eval_bandit.py`, `build_bandit_dataset.py`, `evaluate_all.py`, `evaluate.py`, `ground_truth.py`, `metrics.py`, `train.py`, `ml_registry.py`; golden JSONL files; live DB counts.

## 2. Commands that produced the evidence (reproduce)

```powershell
# from repo root, stack already up (docker compose up -d)
docker compose exec -T backend python scripts/seed_audit_profiles.py
docker compose exec -T backend python scripts/run_phase0_audit.py
docker compose exec -T backend python scripts/run_phase0_employer_audit.py
docker compose exec -T postgres psql -U jobrec -d jobrec -c "SELECT source,count(*),count(embedding) FROM jobs GROUP BY source;"
```

Job corpus top-up (existing script, one query per run):

```powershell
docker compose exec -T backend python scripts/fetch_jobs_live.py --query "java developer" --upsert
```

---

## 3. Feature audit — every UI feature against real jobs and real profiles

Aggregated over 10 real profiles (each feature called per profile through the HTTP API). "Evidence" is an excerpt of the actual response in `audit_feature_runs.json`.

| Feature / tab | Input used | Observed output (representative) | Pass | Evidence |
|---|---|---|---|---|
| **Profile** | 10 CC0 resumes | `GET /profiles/me` returns real headline, `years_of_experience`, `raw_resume_text`, 1–10 linked canonical skills, 768-d embedding | **10/10** | `audit_feature_runs.json` → `feature="Profile"` |
| **AI Matches** | 10 real profiles, 1,117 real jobs | 10 ranked items, `% Match`, readiness band, explanation; `total=40` (30 DB + live); **latency 5.6–40.4 s** | **9/10** | one HTTP 502 — see §4 |
| **Find Jobs** | `q=python` | 20 results, `total=186`, real Adzuna/Jobicy titles, salary, source | **10/10** | `feature="Find Jobs"` |
| **AI Search** | `q=python developer remote` | `mode=llm`, `parsed_filters` echoed, 20 results, `total=44` | **10/10** | `feature="AI Search"` |
| **Skill Gap** | native job `5fc8ae4f…` (5 skills) | `match_score=58.5`, `gap_score=50.1`, readiness 0.33/low, classes strong 0 / partial 1 / transferable 3 / missing 1, `transfer_similarity=0.981` | **10/10** | `feature="Skill Gap"` |
| **Roadmap** | same job | 1+ skill/project steps, per-step rationale, effort hours, readiness before→after | **10/10** | `feature="Roadmap"` |
| **Careers** | 10 real profiles | 3 family suggestions with affinity (e.g. 74.92), overlap 0.797, semantic 0.638, transfer count | **10/10** | `feature="Careers"` |
| **What-If** | add Python (advanced, 5 y) | `before/after` mean score and band counts, persisted simulation; **scores saturated at 100.0** — see §8.3 | **10/10** | `feature="What-If"` |
| **Resume Optimizer** | same job | ATS checks (PASS/WARN/FAIL), missing keywords, `suggestions=[]`, `violations_dropped=0` | **10/10** | `feature="Resume Optimizer"` |
| **Saved / Save Job** | same job | `201` creates `Application(status=saved)` with real job snapshot | **10/10** | `feature="Save Job"` |
| **Employer Hiring** | real posting created via app | posting listed with company, status, skills | **1/1** | `feature="Employer Hiring"` |
| **Employer Talent** | real posting, **0 applicants** | `scored=0`, `candidates=[]` — structurally OK but not meaningful without applicants (§8.5) | **1/1** | `feature="Employer Talent"` |
| **Employer Insights** | real posting | `jd_health.score=100`, checks, peer statistics | **1/1** | `feature="Employer Insights"` |
| **Employer Performance** | real posting | `health=idle`, 0 applicants, 30-day zero-filled series | **1/1** | `feature="Employer Performance"` |
| **Employer What-If** | real posting | `reach_before=40 → reach_after=40`, single-skill levers (e.g. drop FastAPI → 72) | **1/1** | `feature="Employer What-If"` |
| **Admin Config** | — | 8 weights returned (see §8.1) | **1/1** | `feature="Admin Config"` |
| **Admin LLM Usage** | — | 630 calls, 30 flagged, avg 5,736 ms | **1/1** | `feature="Admin LLM Usage"` |
| **Admin Skills** | `q=python` | 354 skills, alias/embedding status | **1/1** | `feature="Admin Skills"` |
| **Admin Duplicates** | 1,115 jobs | **283 duplicate pairs**; **91.1 s** runtime — see §8.4 | **1/1** | `feature="Admin Duplicates"` |
| **Admin Models** | — | 17 registry rows, **13 point to missing artifacts** — see §8.2 | **1/1** | `feature="Admin Models"` |

**Total: 119 / 120 passed.**

---

## 4. The one real failure

`AI Matches` for one real profile returned **HTTP 502**:

```json
{"detail": "AI failure: explain_polish: polish rejected by digit validator (numbers drifted from source)"}
```

Cause: `LLM_STRICT=true` + Gemini rewrite changed a number; the digit-multiset validator correctly rejected it and the strict path raised instead of falling back. This is "no fallback" behaving as specified, but it means **one in ten real user feeds is unavailable**. Decision needed in Phase 4: retry bounded repair, or disable prose polish, rather than silently falling back.

---

## 5. M0–M5 label / lifecycle audit (Phase 0 amendment)

Every reported metric in `master_project_evaluation.json` is **circular, synthetic, simulated, or structurally trivial**. The literal string `SIMULATED` appears **zero times** in the repository.

| Stage | Training/eval data | How labels were made | Split | Verdict | Evidence |
|---|---|---|---|---|---|
| **M0** bi-encoder + cross-encoder | `ml/datasets/embedding_pairs.jsonl` (516 pairs, 45 pos) built from DB interactions of 200 synthetic `synth####@jobrec.test` users; 100 synthetic golden postings + 21 hand-written queries | `seed_synthetic_users.py:259-270` → `ground_truth.py:83` `grade = result.final + tilt + noise` where `result.final` is the **8-factor score**; `sample_label()` buckets it into SAVE/APPLY | profile hash 80/20 seed 42; cross-encoder **val profiles = eval heldout profiles** | **CIRCULAR + LEAKED + SIMULATED**. 21/29 queries and 100/106 corpus items synthetic. | `build_embedding_pairs.py:99-150`; `train_biencoder.py:147-155`; `train_cross_encoder.py:153-157`; `eval_embeddings.py:124-196`; `synthesize_corpus.py:580-602`; master `:7-74` |
| **M1** skill graph / skill2vec | `transfer_pairs.jsonl` 228 pairs; `skill_prereqs.yaml` 37 edges (36 land in DB); synthetic golden postings | Positives = within-cluster pairs; negatives **explicitly filtered to exclude graph edges** (`synthesize_corpus.py:490-491`); same clusters generate skill2vec training sentences (`train_skill2vec.py:130-142`) and GNN `co_used_in_project` edges | **No split** for the reported metric; τ=0.65 and `EPOCHS=60` tuned on the same 228 pairs | **TAUTOLOGY**. `YAML-only` precision 1.0 is guaranteed by construction. `F1=0.9167` is not out-of-sample. | `evaluate.py:166-271`; `synthesize_corpus.py:490-534`; `train_skill2vec.py:37-41,130-142`; `train_skill_graph_gnn.py:226-230`; master `:75-101` |
| **M2** DCN-v2 ranker / ranklet | `train.jsonl` 992 rows / `test.jsonl` 252 rows from synthetic interactions + injected label-0 rows | labels laundered from `score_pair()` via synthetic events; "Heuristic Weighted Sum baseline" **is the label-generating function** | profile-hash 80/20 (clean user separation) but **model epoch-selected on `test.jsonl` and reported on that same `test.jsonl`** (best of 80 epochs); only **6 eval queries / 43 groups** | **CIRCULAR + SELECTION-ON-TEST + SIMULATED**. | `build_datasets.py:69-94,96-135,216,262`; `train_neural_ranker.py:460-489`; `dcn_loss_curve.json:410-419`; master `:102-136` |
| **M3** calibrator | same `test.jsonl` (252 rows, 7 positives = 2.78%) | `y = label >= 4` — score-derived synthetic label; DCN logits from the epoch-38 model selected on those rows | 5-fold row-level OOF **inside `test.jsonl`**; final fit on all validation logits | **CIRCULAR**; "unbiased" only w.r.t. calibrator fit, not DCN selection. | `calibrate.py:31,150-153,156-197,333-348`; master `:137-153` |
| **M4** bandit OPE | Simulated CTR environment (`true_reward_prob`, seeded RNG, hard-coded `theta_true`); real interactions (0 rows) unused | rewards **invented** by formula; `mean_true_ctr` / `mean_best_ctr` are simulator constants | train/test split of simulated rounds; `all_rounds` reports on training rounds too | **SIMULATED presented as real performance** (`status: ok`, no qualifier). | `eval_bandit.py:212-255,321,330,336-338`; `train_bandit.py:39-122`; master `:154-235` |
| **M5** planner–critic | 15 profiles selected by `select(Profile).all()` — all synthetic `@jobrec.test`; 6 native jobs | pass rates are **internal structural checks** (3 agents present, skill in candidate set, phase hours); LLM judge effectively inactive; hallucination forced to 0 | selected and scored in one pass | **SIMULATED / structural validity only** — not roadmap quality. Docs say "real DB (profile, job) pairs" without saying synthetic. | `evaluate_all.py:346-360,399-432,464-466`; `roadmap.py:545-553,587`; master `:237-788` |

**Rule 4 / Rule 6 consequence:** all six master blocks must be relabelled `SIMULATED` or removed; no M0–M5 number may be used as evidence of real-world performance until rebuilt on real data (Phases 1–3). The claim "no synthetic data in reported metrics" is currently false.

### Data-state contradictions with the brief

- Brief says "live Adzuna jobs never persisted" — **false for the DB**: 991 Adzuna rows with embeddings exist from the offline `--upsert` path. True only for request-time live search/save.
- Brief says "0 applications, 0 interactions" — at audit start this was true; the audit itself created 10 `saved` applications.
- 29 non-synthetic seekers exist but are ad-hoc test accounts (`feeddbg_*`, `sync_user_*`, `aanya.*@gmail.com`), **not owner-supplied real profiles**; they were not used.

---

## 6. Cut list — **owner approved 2026-11-19** (execute in Phase 4, not in Phase 0)

### 6.1 Unused config flags (delete)
| Flag | Declared | Evidence |
|---|---|---|
| `api_host` | `app/core/config.py:14` | no reader; Dockerfile hardcodes `0.0.0.0` |
| `api_port` | `app/core/config.py:15` | no reader; compose maps 8000 |
| `embedding_backend` | `app/core/config.py:47` | hardcoded `"biencoder"` at `embeddings.py:59` |
| `embedding_dim` | `app/core/config.py:48` | constant 768 at `embeddings.py:26` |
| `skill2vec_enabled` | `app/core/config.py:94` | zero reads; real switch is env `SKILL_GRAPH_DISABLE_EMBEDDINGS` |
| `synthetic_seed` | `app/core/config.py:100` | only used by `scripts/seed_synthetic_users.py` (delete with it) |
| `openai_base_url_or_none` property | `app/core/config.py:116-118` | provider reads raw field |
| `LGBM_MAX_DELTA`, `LGBM_BLEND_WEIGHT` | `rerank.py:36-37` | dead/misnamed (0.85 blends DCN, not LightGBM) |

Also: `roadmap_weekly_hours` is read via `getattr` at `roadmap.py:467` but never declared.

### 6.2 Fallback / legacy / compatibility / "strict" paths (delete or raise)
- `recommender.py:697-742` `_cold_feed` — dead neutral-prior feed.
- `recommender.py:527-528` `"deterministic"` strategy; `rerank.py:552-561` `"ltr_blend"` — strategy switches to delete in Phase 4.
- `rerank.py:303-351` legacy LightGBM loader; `rerank.py:273-300` `component_vector()` fallback.
- `bandit.py:201-204,206-228,327-328,357-359,385-386` LinUCB compat shims + `LinUCBPolicy` alias (it *is* `NeuralUCBPolicy`).
- `resume_parser.py:376-422,465-466,473-488` regex fallback + `GeminiResumeParser` alias.
- `llm_curation.py:20,46,49,63`; `roadmap.py:139-185,545-553`; `personalization.py:93-102`; `runtime_config.py:24-36,86-101`.
- `skill_graph.py:164-199` DB-edge / joblib / env kill-switch fallbacks.
- `embeddings.py:67-89`, `cross_encoder.py:47-55` fine-tuned→base fallback.
- `calibration.py:5,53-77` "fallback score inputs" docstring + inverse-logit path.
- `nl_search.py:1-8` stale docstring claiming FTS fallback (code already raises).
- `eval_bandit.py:364-398`, `train_bandit.py:203-219`, `evaluate_all.py:66-80,139-168,195-253` fallback branches.
- `main.py:86-90` `LlmStrictError → 502` handler — keep only if strict path is redesigned in Phase 4.

### 6.3 Dead / unreachable code
- `backend/app/services/admin_governance/` — `__pycache__` only, no `.py`, no import.
- Stale `.pyc`-only modules: `app/core/__pycache__/ratelimit.*`, `app/services/__pycache__/{effort_estimator,adzuna_ingest,skill_quality}.*`, `backend/ml/__pycache__/extraction_eval.*`.
- `app/api/v1/applications.py` — one-line re-export shim, not wired.
- Unreachable frontend API helpers: `getOnboardingPairs/getOnboardingFlow/nextOnboardingQuestion/completeOnboarding` (`api.ts:697-736`), `getPreferences/resetPreferences` (`:550,555`), `getProjectMap/getProjectBenefits` (`:584,592`), `getApplicationHistory` (`:820`), `HealthPanel` component (never imported).
- Backend routes with no UI consumer: `/onboarding/*` (`api/onboarding.py:47,53,59,81`), `/system/status`, `/monitoring/summary`, `/jobs/{id}/project-map`, `/profiles/me/project-benefits`.
- ML scripts with no caller: `ml/eval_embeddings.py`, `ml/build_bandit_dataset.py`, `ml/train_score_weights.py`, `ml/build_embedding_pairs.py` (string refs only).

### 6.4 Tests needing external state (must become hermetic in Phase 4)
| Tests | Dependency |
|---|---|
| `test_crud.py`, `test_fts.py` | live server + seeded user `aanya.seeker@example.com` |
| `test_recommender.py`, `test_simulator.py`, `test_discovery.py` | seeded user + seeded jobs + DCN/calibrator artifacts (`conftest.py:47-53` points at `localhost:55432`) |
| `test_roadmap.py`, `test_eval_regression.py` | committed artifacts; 4+ gates `pytest.skip` when absent; `test_eval_regression.py:256,260-261` asserts stale **30** features and names that no longer exist (actual 31) |
| `test_nl_search.py` | DB + expects removed FTS fallback (stale, would fail) |
| `verify_phase1_e2e.py`, `verify_phase2_e2e.py` | live HTTP + DB |
| OK as-is (pure unit) | `test_explanation*`, `test_strict`, `test_bandit`, `test_resume_parser`, `test_llm_validators`, `test_ingest`, `test_scoring`, `test_mmr`, `test_normalizer`, `test_gap_engine` |

---

## 7. Documentation claims with no evidence (rule 9 — correct in Phase 4 PR)

| Claim | Location | Reality |
|---|---|---|
| "Domain-tuned BGE + cross-encoder" at runtime | `README.md:19`, `PROJECT_STATE.md:26`, `DESIGN.md:6` | `embedding_finetuned_path=""`, `cross_encoder_finetuned_path=""` → base models load at runtime (`embeddings.py:76`, `cross_encoder.py:55`). Fine-tuned weights only exist as evaluation artifacts. |
| "Relational GraphSAGE … used in runtime paths" | `README.md:20`, `PROJECT_STATE.md:27` | runtime loads `skill2vec_v*.joblib`; committed `skillgraph_gnn_v*.json` are never loaded (wrong extension at `skill_graph.py:182`). |
| "31-feature schema" | `README.md:21` | true in code but the only test asserts 30 with stale names → not backed by a passing test. |
| "Evaluated on real DB (profile, job) pairs" | `README.md:24`, `PROJECT_STATE.md:31` | literally true but the 15 profiles are **synthetic** `@jobrec.test`; must say so. |
| "≥ gates" | `DESIGN.md:603-609` | 4 of 6 artifact-dependent tests skip when artifacts absent; M2 eval is 6 queries; M3 positive rate 2.8%. |
| "no fallbacks / AI-mandatory" | `config.py:30,57-58,95`, `.env.example:35,53-54` | contradicted by `_cold_feed`, deterministic strategy, regex/template fallbacks (§6.2) and `.env.example:35` itself. |
| "Demo credentials (if present in DB)" | `README.md:92-94` | no committed seeder creates them; move to dev-only seed script (Phase 1 amendment). |
| "Model weights may be local/untracked" | `README.md:161`, `PROJECT_STATE.md:79` | `biencoder_finetuned/model.safetensors` and `cross_encoder_finetuned/model.safetensors` are present on disk. |
| `EXPLAIN_LLM` / `LLM_STRICT` / `SKILL2VEC_ENABLED` defaults | `.env.example:37,75,80` | contradict `config.py:34,36,94`; skill2vec flag is dead. |
| "`ltr_blend`/LightGBM, α=0.35, ±15 pts" | `DESIGN.md:140,158,234,239,648` | code uses DCN-v2, `LGBM_BLEND_WEIGHT=0.85` mislabeled, ±15 constant dead. |

---

## 8. Critical runtime findings from the real-data audit

1. **Live scoring weights are not the documented weights.** `GET /admin/config` returns
   `semantic 0.0001, skill 0.4493, experience 0.0001, education 0.0001, project 0.3965, location 0.0001, salary 0.0001, interest 0.1536`
   (sum 1.0) instead of the documented `0.30/0.25/0.15/0.10/0.05/0.05/0.05/0.05`. The `score_weights_v1.json` artifact was learned from the circular synthetic labels (§5) and is loaded at runtime by `runtime_config.py`. **Consequence:** the "8-factor explainable score" currently in production is dominated by skill + project weights derived from a label function. This must be removed before Phase 3 baselines are meaningful.
2. **Model registry is broken.** 13 of 17 rows point to artifacts that do not exist (e.g. `calibrator_v5`, `ranklet_v3..v6`, `skill2vec_v1,v4..v6`). Serving selects by filename glob, not registry — confirming `README`/`DESIGN` claims about registry-driven models are false.
3. **Score saturation.** What-If reported `mean_score=100.0` before and after adding a skill; band counts unchanged (0 low / 100 medium). The displayed "% Match" is saturated on real jobs, so it cannot discriminate. Likely caused by double calibration (`recommender.py:484-522` + `explanation.py:226-239`) and the corrupted weights in finding 1.
4. **Admin duplicate scan is O(n²).** 91.1 s for 1,115 jobs, returning 283 pairs — must be bounded/indexed before it is usable.
5. **Employer ranking was structurally exercised but not validated.** There are **0 real applications/interactions** in the DB, so Talent returned `scored=0` and What-If `avg_fit=null`. No claim about applicant-ranking quality can be made until real applications exist (Phase 1 exposure logging).
6. **One feed in ten 502s** under `LLM_STRICT=true` when Gemini rewrites drift a number (§4).
7. **1 native job has no embedding** (5 of 6); all 1,111 provider jobs have embeddings.

---

## 9. Open risks / decisions required

- [ ] Owner to confirm the CC0 livecareer resumes are acceptable as the "10 real profiles" substitute (they were authorised in this session; recorded in `DATA.md`).
- [ ] Decide the strict-LLM 502 remediation for Phase 4 (retry vs. disable prose polish).
- [ ] Confirm removal of the learned `score_weights_v1.json` artifact and reset to documented defaults before Phase 2 baselines.
- [ ] Rule 8: XING datasets are forbidden; CareerBuilder / LinkedIn / ESCO / O\*NET licence checks are outstanding Phase 2 items.
- [ ] Provider ToS on storage/attribution for Adzuna/Jobicy to be documented in Phase 1.

## 10. Files added in Phase 0

| File | Reason |
|---|---|
| `backend/ml/reports/audit.md` | This audit |
| `backend/ml/reports/audit_feature_runs.json` | 120 request/response evidence records |
| `backend/ml/DATA.md` | Verified dataset provenance and licences |
| `backend/ml/data/external/audit_real_profiles_10.json` | 10 real CC0 resumes with provenance |
| `backend/scripts/seed_audit_profiles.py` | Dev-only loader for the real audit profiles (idempotent) |
| `backend/scripts/run_phase0_audit.py` | Reproducible feature audit runner |
| `backend/scripts/run_phase0_employer_audit.py` | Employer-side audit runner |

**No feature code was changed in Phase 0.** No commit/PR was created in this session — the working tree holds these files for review.
