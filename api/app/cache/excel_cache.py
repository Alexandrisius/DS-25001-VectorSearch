"""Excel cache в Redis (общий для API и Celery worker).

Раньше данные Excel хранились в in-memory _app_state_holder внутри API процесса.
Celery worker их не видел, а еще payload 142k строк (28 MB JSON) не помещался
в Redis message queue (connection reset by peer).

Решение: сохраняем Excel данные в Redis как key/value с TTL.
Передаём в Celery только cache_key (16 байт), worker читает данные из Redis.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from app.db.redis import get_redis

CACHE_TTL_SECONDS = 3600  # 1 час — достаточно для импорта
CACHE_KEY_PREFIX = "ksr:excel:"


async def save_excel_to_cache(cache_key: str, data: dict[str, Any]) -> None:
    """Сохранить Excel данные в Redis.

    Args:
        cache_key: Уникальный ключ (UUID)
        data: {headers, data (list of dicts), filename, ts}
    """
    redis = get_redis()
    payload = json.dumps(data, ensure_ascii=False, default=str)
    await redis.setex(f"{CACHE_KEY_PREFIX}{cache_key}", CACHE_TTL_SECONDS, payload)


async def load_excel_from_cache(cache_key: str) -> dict[str, Any] | None:
    """Загрузить Excel данные из Redis.

    Returns:
        {headers, data, filename, ts} или None если не найдено
    """
    redis = get_redis()
    raw = await redis.get(f"{CACHE_KEY_PREFIX}{cache_key}")
    if raw is None:
        return None
    return json.loads(raw)


async def delete_excel_from_cache(cache_key: str) -> None:
    """Удалить Excel данные из Redis."""
    redis = get_redis()
    await redis.delete(f"{CACHE_KEY_PREFIX}{cache_key}")


async def cleanup_old_excel_cache(max_age_seconds: int = 3600) -> int:
    """Удалить старые Excel записи (>max_age_seconds).

    Returns: количество удалённых ключей.
    """
    redis = get_redis()
    pattern = f"{CACHE_KEY_PREFIX}*"
    deleted = 0
    async for key in redis.scan_iter(match=pattern):
        # Проверяем TTL — оставшиеся с истёкшим TTL удалятся автоматически
        ttl = await redis.ttl(key)
        if ttl == -1:  # нет TTL — удаляем вручную
            await redis.delete(key)
            deleted += 1
    return deleted


__all__ = [
    "save_excel_to_cache",
    "load_excel_from_cache",
    "delete_excel_from_cache",
    "cleanup_old_excel_cache",
    "CACHE_TTL_SECONDS",
    "CACHE_KEY_PREFIX",
]
