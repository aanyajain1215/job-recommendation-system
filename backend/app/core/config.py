from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: str = "development"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    database_url: str
    cors_origins: str = "http://localhost:3000"
    jwt_secret_key: str = "09d25e094faa6ca2556c818166b7a9563b93f7099f6f0f4caa6cf63b88e8d3e7"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    refresh_token_expire_days: int = 7
    # LLM resume parsing — AI-only mode (no regex fallback)
    gemini_api_key: str = ""

    # ---- LLM provider abstraction (AI-mandatory) ----
    openai_api_key: str = ""
    openai_base_url: str = ""  # optional OpenAI-compatible proxy
    llm_provider: str = "openai"  # "openai" | "gemini"
    llm_model: str = "gpt-4o-mini"
    # AI-mandatory: LLM must be enabled and available; no deterministic fallbacks.
    llm_enabled: bool = True
    llm_timeout_seconds: int = 30
    # P6: LLM rewrites explanation prose (numbers guarded by validators).
    explain_llm: bool = True
    # Strict mode: any AI path failure raises (no silent fallback) so issues are visible.
    llm_strict: bool = True
    # How many recommender-feed items get LLM explanation polish per request.
    # A full 20-item feed would fire ~20 back-to-back requests and trip the
    # provider's per-minute rate limit; past top-N the deterministic
    # template ships (job detail stays polished — it is a single call).
    explain_polish_top_n: int = 3

    # ---- Embeddings / M0 (research-grade: domain-tuned bi-encoder + cross-encoder) ----
    # Bi-encoder for retrieval (768-d). Use fine-tuned path when available.
    embedding_model: str = "BAAI/bge-base-en-v1.5"
    embedding_finetuned_path: str = ""  # e.g. ml/artifacts/biencoder_finetuned
    embedding_backend: str = "biencoder"  # "biencoder" required in AI-strict mode
    embedding_dim: int = 768
    # Cross-encoder for precise reranking of top-K candidates
    cross_encoder_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    # Fine-tuned on real Resume-JD Fit pairs (ml/train_cross_encoder_real.py); resolved
    # relative to ml/artifacts/. Falls back to cross_encoder_model if weights are absent.
    cross_encoder_finetuned_path: str = "cross_encoder_finetuned"
    cross_encoder_top_k: int = 50
    cross_encoder_batch_size: int = 16

    # ---- Recommender (plan §4/§6) ----
    # AI-first: prefer the learned ranklet (M2) as the primary match/ranking
    # decision when a valid artifact exists. Falls back safely to deterministic
    # scoring if the model/manifest is missing or incompatible.
    recommender_strategy: str = "ltr_full"  # "deterministic" | "ltr_blend" | "ltr_full"
    mmr_lambda: float = 0.7
    exploration_rate: float = 0.1667  # 1-in-6 feed slots
    transfer_similarity_threshold: float = 0.65

    # ---- Contextual bandit / RL exploration ----
    bandit_enabled: bool = True
    bandit_exploration_policy: str = "linucb"  # "random" | "linucb"
    bandit_alpha: float = 0.8
    bandit_temperature: float = 0.5
    bandit_min_pool: int = 2
    bandit_online_updates: bool = True

    # ---- Skill Gap Engine (plan §8) ----
    gap_strong_min_years: float = 2.0

    # ---- Career Roadmap Generator (plan §9) ----
    roadmap_weak_partial_importance: float = 1.4
    roadmap_phase_max_hours: float = 25.0
    roadmap_project_every_n_skills: int = 2

    # ---- Alternative Career Discovery (plan §11) ----
    discovery_threshold: float = 55.0          # τ — minimum affinity to suggest
    discovery_weight_strong: float = 1.0
    discovery_weight_partial: float = 0.6
    discovery_weight_transfer: float = 0.7     # × transfer similarity
    discovery_weight_semantic: float = 0.3     # blend = 0.7·overlap + 0.3·semantic

    # ---- LLM layer (plan §15) ----
    llm_cache_ttl_seconds: int = 3600
    llm_cache_max_entries: int = 256
    llm_max_repair_turns: int = 1

    # ---- Trained model suite M1–M3 (AI-mandatory) ----
    # M1: enable learned skill2vec transfer signals.
    skill2vec_enabled: bool = True
    # M3: calibrated readiness required (no raw fallback).
    readiness_calibrator_enabled: bool = True
    readiness_band_high: float = 0.80       # calibrated bands (plan §6 M3)
    readiness_band_medium: float = 0.60
    calibrator_positive_min: int = 4        # graded label ≥ save = positive outcome
    synthetic_seed: int = 1729              # deterministic bootstrap seed (plan §6 M2)

    # ---- Live ingestion pipeline (plan §20.1) ----
    adzuna_app_id: str = ""                 # Adzuna is the primary job API
    adzuna_app_key: str = ""
    adzuna_country: str = "in"
    ingest_http_timeout: int = 20
    ingest_delay_seconds: float = 0.5       # polite rate limit between requests

    # ---- Ops ----
    rate_limit_per_minute: int = 120

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def openai_base_url_or_none(self) -> str | None:
        return self.openai_base_url or None


@lru_cache
def get_settings() -> Settings:
    return Settings()
