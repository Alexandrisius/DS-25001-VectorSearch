"""Celery application — для фоновых задач (импорт и др.)."""
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
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_default_queue="ksr_default",
    task_routes={
        "app.workers.tasks.import_task": {"queue": "imports"},
        "app.workers.tasks.reindex_task": {"queue": "imports"},
    },
    # Beat: периодические задачи (reconciler)
    beat_schedule={
        "reconcile-postgres-qdrant": {
            "task": "app.workers.tasks.reconcile_task",
            "schedule": crontab(minute="*/15"),  # каждые 15 минут
        },
    },
)

__all__ = ["celery_app"]
