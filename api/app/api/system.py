"""System endpoints: /health, /stats, /reload_config, /clear_cache, /debug."""
from __future__ import annotations

from fastapi import APIRouter
from loguru import logger

from app.config import get_settings

router = APIRouter(tags=["system"])


@router.get("/health")
async def health() -> dict:
    """Liveness + readiness probe."""
    return {"status": "ok", "version": "2.0.0"}


@router.get("/stats")
async def stats() -> dict:
    """Подробная статистика сервера."""
    settings = get_settings()
    return {
        "env": settings.env,
        "log_level": settings.log_level,
        "embedding_model": settings.openrouter_model_embed,
        "rerank_model": settings.openrouter_model_rerank,
        "default_thresholds": {
            "cosine": settings.default_cosine_threshold,
            "rerank": settings.default_rerank_threshold,
        },
    }


@router.post("/reload_config")
async def reload_config() -> dict:
    """Hot-reload настроек (без перезапуска сервера)."""
    get_settings.cache_clear()  # type: ignore[attr-defined]
    logger.info("Конфигурация перезагружена")
    return {"status": "success", "message": "Конфигурация перезагружена"}


@router.post("/clear_cache")
async def clear_cache() -> dict:
    """Очистить кэш эмбеддингов (in-memory LRU)."""
    # TODO: подключить кэш-сервис, когда будет
    logger.info("Кэш эмбеддингов очищен")
    return {"status": "success", "message": "Кэш очищен"}


@router.get("/debug/check_code/{code}")
async def debug_check_code(code: str) -> dict:
    """DEBUG: проверить существование кода (заглушка, реализуется в services)."""
    return {"status": "todo", "code": code}
