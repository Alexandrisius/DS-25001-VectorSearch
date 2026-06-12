"""Celery application — broker, beat, worker config."""
from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "ksr",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    # Cancel-safety: если worker умрёт в середине импорта — task будет
    # пере-доставлен, не потеряется. Благодаря chunked pipeline данные
    # из завершённых чанков уже в БД.
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    # Избежание memory leak: перезапуск child worker после N задач.
    # По best practices — каждые 100-1000 задач (в нашем случае импорт
    # 142k записей = 1 задача, так что это сработает только на reconcile).
    worker_max_tasks_per_child=50,
    # Worker слушает ОБЕ очереди: ksr_default (для reconcile) и imports (для импорта).
    # Задаётся через command: celery -A ... worker -Q imports,ksr_default
    task_default_queue="ksr_default",
    # Используем только default queue (imports не нужен как отдельный)
    task_routes={},
    beat_schedule={
        "reconcile-postgres-qdrant": {
            "task": "app.workers.tasks.reconcile_task",
            "schedule": crontab(minute="*/15"),
        },
    },
)

__all__ = ["celery_app"]
