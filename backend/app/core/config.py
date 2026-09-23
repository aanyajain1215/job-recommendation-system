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
    # LLM resume parsing — leave blank to use the regex fallback parser
    gemini_api_key: str = ""

    # ---- LLM provider abstraction (plan §15: OpenAI default, Gemini kept) ----
    openai_api_key: str = ""
    openai_base_url: str = ""  # optional OpenAI-compatible proxy
    llm_provider: str = "openai"  # "openai" | "gemini"
    llm_model: str = "gpt-4o-mini"
    llm_timeout_seconds: int = 30

    # ---- Embeddings (plan §4/§13) ----
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    # "auto" = MiniLM if importable, else deterministic hashing fallback
    embedding_backend: str = "auto"  # "auto" | "minilm" | "hashing"

    # ---- Recommender (plan §4/§6) ----
    recommender_strategy: str = "deterministic"  # "deterministic" | "ltr_blend" | "ltr_full"
    mmr_lambda: float = 0.7
    exploration_rate: float = 0.1667  # 1-in-6 feed slots
    transfer_similarity_threshold: float = 0.65

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

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def openai_base_url_or_none(self) -> str | None:
        return self.openai_base_url or None


@lru_cache
def get_settings() -> Settings:
    return Settings()
