"""Application configuration (Pydantic v2 Settings)."""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Централизованная конфигурация приложения.

    Все настройки читаются из переменных окружения / .env файла.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ===== General =====
    env: Literal["development", "staging", "production"] = "production"
    log_level: str = "INFO"
    cors_origins: str = "*"
    server_host: str = "0.0.0.0"
    server_port: int = 8000

    # ===== Database (PostgreSQL) =====
    postgres_db: str = "ksr"
    postgres_user: str = "ksr"
    postgres_password: str = Field(default="", description="POSTGRES_PASSWORD")
    database_url: str = Field(..., description="asyncpg URL приложения")
    sync_database_url: str = Field(..., description="psycopg2 URL для Alembic")

    # ===== Qdrant =====
    qdrant_url: str = "http://qdrant:6333"
    qdrant_api_key: str = ""

    # ===== Redis =====
    redis_url: str = "redis://redis:6379/0"
    celery_broker_url: str = "redis://redis:6379/0"
    celery_result_backend: str = "redis://redis:6379/1"

    # ===== Security =====
    admin_password_hash: str = ""
    jwt_secret_key: str = "change-me"
    jwt_expire_hours: int = 8
    jwt_algorithm: str = "HS256"
    encryption_key: str = ""  # Fernet key for api_key encryption

    # ===== Rate limit =====
    login_max_attempts: int = 5
    login_lockout_minutes: int = 5

    # ===== OpenRouter (defaults, can be overridden in DB) =====
    openrouter_api_key: str = ""
    openrouter_model_embed: str = "qwen/qwen3-embedding-4b"
    openrouter_model_rerank: str = "qwen/qwen3-rerank-8b"
    openrouter_batch_size: int = 10
    openrouter_max_workers: int = 3
    openrouter_request_timeout: int = 60
    openrouter_max_retries: int = 3

    # ===== Search =====
    top_k_qdrant: int = 500
    max_for_rerank: int = 100
    max_results: int = 100
    default_cosine_threshold: float = 0.45
    default_rerank_threshold: float = 0.6
    embedding_cache_size: int = 15000

    # ===== BM25 =====
    bm25_enabled: bool = True
    bm25_top_k: int = 200
    bm25_max_retrieve: int = 100
    hybrid_rerank_limit: int = 200

    # ===== Import =====
    import_batch_size_api: int = 10
    import_batch_size_local: int = 32
    folder_rebuild_batch: int = 100

    # ===== Telemetry =====
    sentry_dsn: str = ""

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Singleton-аксессор для настроек."""
    return Settings()  # type: ignore[call-arg]
