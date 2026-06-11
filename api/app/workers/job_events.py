"""Helper для публикации прогресса задач в Redis pub/sub.

Celery worker вызывает `publish_job_progress(job_id, payload)` после каждого
обновления job.progress / job.details. WebSocket endpoint
(`/admin/jobs/{id}/ws`) подписан на канал `job:{id}` и проксирует
события клиенту.

Использует ОТДЕЛЬНЫЙ sync redis клиент — потому что зовётся из sync callback
внутри активного event loop (asyncio.run_until_complete() тогда падает с
"This event loop is already running").
"""
from __future__ import annotations

import json
import logging
from threading import Lock
from typing import Any

import redis as redis_sync

from app.config import get_settings

logger = logging.getLogger(__name__)

_sync_redis: redis_sync.Redis | None = None
_lock = Lock()


def _get_sync_redis() -> redis_sync.Redis:
    global _sync_redis
    if _sync_redis is None:
        with _lock:
            if _sync_redis is None:
                settings = get_settings()
                _sync_redis = redis_sync.from_url(
                    settings.redis_url,
                    encoding="utf-8",
                    decode_responses=True,
                    socket_connect_timeout=2,
                    socket_timeout=2,
                )
    return _sync_redis


def publish_job_progress(job_id: str, payload: dict[str, Any]) -> None:
    """Опубликовать событие прогресса в Redis pub/sub канал `job:{job_id}`.

    Безопасно для sync-контекста (из callback'ов внутри активного event loop).
    Использует sync redis клиент, не блокирует loop.
    При ошибке не падает (best-effort).
    """
    try:
        redis = _get_sync_redis()
        channel = f"job:{job_id}"
        body = json.dumps(payload, ensure_ascii=False, default=str)
        redis.publish(channel, body)
    except Exception as e:
        logger.debug(f"[publish_job_progress] failed for {job_id}: {e}")


__all__ = ["publish_job_progress"]
