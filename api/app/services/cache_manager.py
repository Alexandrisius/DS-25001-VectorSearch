"""Process-wide cache registry.

BM25 indices and EmbeddingService singletons live here.
Mutated by data services (import/material update) to invalidate stale caches.

Note: with multi-worker uvicorn each worker has its own copy.
For cross-worker sharing use Redis (future work).
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.services.search_service import BM25Index


class CacheManager:
    """Singleton-style cache for BM25 and embedding across requests/workers."""

    bm25_indices: dict[str, Any] = {}  # str -> BM25Index (duck-typed to avoid circular import)

    @classmethod
    def get_bm25(cls, name: str) -> Any | None:
        return cls.bm25_indices.get(name)

    @classmethod
    def set_bm25(cls, name: str, idx: Any) -> None:
        cls.bm25_indices[name] = idx

    @classmethod
    def invalidate_bm25(cls, name: str) -> None:
        cls.bm25_indices.pop(name, None)

    @classmethod
    def all_bm25(cls) -> dict[str, Any]:
        return dict(cls.bm25_indices)


__all__ = ["CacheManager"]
