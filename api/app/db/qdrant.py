"""Qdrant client singleton.

Используем gRPC вместо HTTP (по умолчанию 6334) — обходит 32 MB HTTP лимит
(Qdrant hardcoded в actix-web), 30-50% быстрее, и поддерживает bulk
upsert без chunking на стороне клиента.

См. https://qdrant.tech/documentation/quickstart-cloud/#grpc
"""
from __future__ import annotations

from functools import lru_cache

from qdrant_client import QdrantClient

from app.config import get_settings


# gRPC max message size — увеличиваем для bulk upsert.
# 1000 vectors × 4096d × 4 bytes = 16 MB binary, плюс payload ~5-10 MB.
# Default 4 MB слишком мало. 100 MB — запас.
_GRPC_MAX_MESSAGE_LENGTH = 100 * 1024 * 1024  # 100 MB


@lru_cache(maxsize=1)
def get_qdrant_client() -> QdrantClient:
    """Singleton-клиент Qdrant через gRPC."""
    settings = get_settings()
    common_kwargs: dict = {
        "timeout": 60,
        "prefer_grpc": True,
        "grpc_port": 6334,
        "grpc_options": {
            "grpc.max_send_message_length": _GRPC_MAX_MESSAGE_LENGTH,
            "grpc.max_receive_message_length": _GRPC_MAX_MESSAGE_LENGTH,
        },
    }
    if settings.qdrant_api_key:
        return QdrantClient(
            url=settings.qdrant_url,
            api_key=settings.qdrant_api_key,
            **common_kwargs,
        )
    return QdrantClient(url=settings.qdrant_url, **common_kwargs)


def close_qdrant() -> None:
    """Закрыть клиент (при shutdown)."""
    get_qdrant_client.cache_clear()


__all__ = ["get_qdrant_client", "close_qdrant"]
