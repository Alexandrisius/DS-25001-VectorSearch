"""Redis client (для кэша эмбеддингов и сессий)."""
from __future__ import annotations

from functools import lru_cache

import redis.asyncio as aioredis

from app.config import get_settings


@lru_cache(maxsize=1)
def get_redis() -> aioredis.Redis:
    """Singleton-клиент Redis (async)."""
    settings = get_settings()
    return aioredis.from_url(
        settings.redis_url,
        encoding="utf-8",
        decode_responses=True,
        max_connections=20,
    )


async def close_redis() -> None:
    client = get_redis()
    await client.aclose()


__all__ = ["get_redis", "close_redis"]
