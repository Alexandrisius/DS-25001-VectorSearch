"""Qdrant client singleton."""
from __future__ import annotations

from functools import lru_cache

from qdrant_client import QdrantClient

from app.config import get_settings


@lru_cache(maxsize=1)
def get_qdrant_client() -> QdrantClient:
    """Singleton-клиент Qdrant."""
    settings = get_settings()
    if settings.qdrant_api_key:
        return QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key, timeout=60)
    return QdrantClient(url=settings.qdrant_url, timeout=60)


def close_qdrant() -> None:
    """Закрыть клиент (при shutdown)."""
    get_qdrant_client.cache_clear()


__all__ = ["get_qdrant_client", "close_qdrant"]
