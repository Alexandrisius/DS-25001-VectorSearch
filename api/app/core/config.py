"""Application configuration (Pydantic v2 Settings)."""
from __future__ import annotations

import os
from functools import lru_cache
from typing import Literal

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Загружаем .env ДО создания Settings.
# Pydantic v2 имеет баг с `$` в env-файлах — интерпретирует `$2b$`
# (bcrypt-хеш) и Fernet-ключи как переменные окружения, ломая секреты.
# python-dotenv НЕ интерполирует переменные, поэтому загружаем через него.
load_dotenv(override=True)


class Settings(BaseSettings):
    """Централизованная конфигурация приложения.

    Все настройки читаются из переменных окружения.
    Секреты (ADMIN_PASSWORD_HASH, JWT_SECRET_KEY, ENCRYPTION_KEY) — через @property,
    чтобы избежать проблем с интерполяцией `$` в pydantic.
    """

    model_config = SettingsConfigDict(
        env_file=None,  # Загружаем через load_dotenv() выше
        case_sensitive=False,
        extra="ignore",
    )

    # ===== Secrets (через @property — НЕ поля!) =====
    @property
    def admin_password_hash(self) -> str:
        """Bcrypt хеш пароля админа (os.getenv чтобы избежать `$`-интерполяции)."""
        return os.getenv("ADMIN_PASSWORD_HASH", "")

    @property
    def jwt_secret_key(self) -> str:
        """JWT signing key (os.getenv)."""
        return os.getenv("JWT_SECRET_KEY", "change-me")

    @property
    def encryption_key(self) -> str:
        """Fernet encryption key (os.getenv)."""
        return os.getenv("ENCRYPTION_KEY", "")

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

    # ===== JWT =====
    jwt_expire_hours: int = 8
    jwt_algorithm: str = "HS256"

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
    bm25_max_retrieve: int = 500
    hybrid_rerank_limit: int = 500

    # ===== Phase 4: RRF + MMR + adaptive threshold =====
    # These are defaults; the actual values used at search time come from the
    # Collection model so admins can tune per-collection via the admin UI.
    # The per-collection values are written by SettingsService via PUT /config.
    rrf_k: int = 60
    rrf_dense_weight: float = 1.0
    rrf_bm25_weight: float = 0.7
    mmr_lambda: float = 0.7
    mmr_pool_size: int = 100
    # Adaptive threshold: if max rerank_score >= adaptive_confident_min,
    # "confident" → top-N (max_results). If in [adaptive_uncertain_min,
    # confident_min) — "uncertain" → top-5 + UI hint. If < adaptive_uncertain_min
    # — fallback to top-N by cosine similarity (>= fallback_cosine_min).
    adaptive_confident_min: float = 0.5
    adaptive_uncertain_min: float = 0.15
    fallback_cosine_min: float = 0.30

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
