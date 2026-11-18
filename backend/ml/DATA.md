# JobRec — Data sources, licences and provenance

> Status: **Phase 0 evidence file**. Only sources actually verified/used are listed.
> Rule: if a licence is unavailable, STOP and report — do not substitute silently.

## 1. Real profiles used in Phase 0 (10)

| Property | Value |
|---|---|
| Dataset | [`opensporks/resumes`](https://huggingface.co/datasets/opensporks/resumes) (mirror of Kaggle `snehaanbhawal/resume-dataset`) |
| Licence | **CC0-1.0** (public domain; verified on the HF dataset card and the Kaggle data card) |
| Content | 2,484 real anonymised resumes (plain text + HTML + PDF) scraped from public livecareer.com resume examples; 24 occupational categories |
| Selection | One resume from each of 10 categories: HR, INFORMATION-TECHNOLOGY, ENGINEERING, FINANCE, BUSINESS-DEVELOPMENT, SALES, DESIGNER, DIGITAL-MEDIA, ACCOUNTANT, CONSULTANT |
| Committed sample | `backend/ml/data/external/audit_real_profiles_10.json` (ID, category, full `Resume_str`, source URL, licence) |
| PII | Names/companies in the source are anonymised placeholders ("Company Name", "City, State"). No contact details are used. |
| Synthetic? | **NO.** These are real resume documents. They are *audit-only* — not used to train or tune any model in Phase 0. |
| Loader | `python scripts/seed_audit_profiles.py` (dev-only, idempotent, emails `audit_livecareer_*@audit.jobrec.io`) |

Download command (PowerShell, from repo root):

```powershell
# Dataset rows API — no auth needed for this public CC0 dataset
curl.exe -sS "https://datasets-server.huggingface.co/rows?dataset=opensporks/resumes&config=default&split=train&offset=0&length=100"
```

## 2. Real jobs used in Phase 0 (1,116)

| Source | Rows | Embedding | Notes |
|---|---:|---:|---|
| Adzuna (India) | 991 | 991 | Fetched at request time by the existing `scripts/fetch_jobs_live.py --upsert`; stored as real DB rows with `source='adzuna'`, external id, permanent `/details/<id>` apply URL. |
| Jobicy | 120 | 120 | Keyless public remote-jobs API, same ingestion path. |
| Native (platform-posted) | 6 | 5 | 5 from the old `seed_jobs.py` snapshot + 1 created through the app's **Post a job** feature during this audit. These are real-format postings, not synthetic users. |
| **Total** | **1,117** | **1,116** | One native job lacks an embedding (pre-existing). |

Attribution: each row carries `source` + `external_url` (apply link back to provider), consistent with the project's existing design. **Open risk:** Adzuna/Greenhouse/Lever/Ashby storage and attribution terms still need explicit documentation in Phase 1 (Rule 8). This Phase 0 top-up reused the existing ingestion path; no new provider was added.

## 3. Datasets checked but NOT used (Rule 8 — stop and report)

| Source | Status | Reason |
|---|---|---|
| **XING RecSys Challenge 2016 / 2017** | **UNAVAILABLE / forbidden** | Download requires a XING account and acceptance of rules; data is "semi-synthetic", all rights reserved by XING AG, academic use only, sharing strictly forbidden, no commercial use. Cannot be used for this project. |
| **TalentCLEF 2026 Task A** | Available (Zenodo, CC-BY-4.0) but **not usable as real profiles** | Corpus documents are *synthetically generated* from structured real data; using them to claim real-world performance would violate Rule 4. Candidate for Phase 2/3 only if relabelled SIMULATED. |
| **CareerBuilder Kaggle** | Not retrieved | Requires Kaggle authentication; Phase 2 item — verify licence/availability before use. |
| **LinkedIn Job Postings Kaggle** | Not retrieved | Job-side only; Phase 2 item — verify licence/availability before use. |
| **ESCO / O\*NET** | Not retrieved | Phase 3 taxonomy item — verify licence before use. |
| **SkillSpan** (`jjzha/skillspan`) | **Available**, CC-BY-4.0, 11,543 annotated spans, real job postings | Suitable for the Phase 3 skill-extraction benchmark. Not used in Phase 0. |
| `MikePfunk28/resume-training-dataset` | Rejected | MIT but gated ("agree to share HF info") and largely conversational/generated content — provenance unsuitable for "real profiles". |
| `datasetmaster/resumes` | Rejected | Card explicitly mixes **real and Faker-synthetic** resumes — Rule 4 prohibits use as a real-only source. |

## 4. Prohibited data

No synthetic profiles, synthetic interactions, or formula-derived labels were used anywhere in the Phase 0 feature audit. The pre-existing 230 synthetic seekers and 0 real interactions in the DB are documented as a defect in `ml/reports/audit.md`.
