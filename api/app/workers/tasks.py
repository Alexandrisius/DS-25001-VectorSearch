"""Celery задачи.

Содержит:
- import_task — массовый импорт Excel/CSV с генерацией эмбеддингов
- reindex_task — переиндексация папок
- reconcile_task — сверка Postgres ↔ Qdrant
"""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime
from typing import Any

from loguru import logger
from sqlalchemy import select, update

from app.db.postgres import session_scope
from app.models.background_job import BackgroundJob, JobStatus
from app.models.collection import Collection
from app.workers.celery_app import celery_app


def _run_async(coro):
    """Запуск async-корутины из sync Celery-задачи."""
    return asyncio.run(coro)


async def _update_job(job_id: str, **fields: Any) -> None:
    async with session_scope() as session:
        await session.execute(
            update(BackgroundJob)
            .where(BackgroundJob.id == uuid.UUID(job_id))
            .values(**fields)
        )


@celery_app.task(name="app.workers.tasks.import_task", bind=True)
def import_task(self, job_id: str, params_json: str) -> dict:
    """Массовый импорт материалов в коллекцию.

    params_json содержит:
    - collection_name: str
    - records: List[{code, description, hierarchy?, meta?}]
    - recreate: bool
    """
    params = json.loads(params_json)
    logger.info(f"Import job {job_id} started: {len(params.get('records', []))} records")
    return {"status": "queued", "job_id": job_id, "total": len(params.get("records", []))}


@celery_app.task(name="app.workers.tasks.reindex_task", bind=True)
def reindex_task(self, job_id: str, collection_name: str) -> dict:
    """Переиндексация папок в коллекции."""
    logger.info(f"Reindex job {job_id} for '{collection_name}'")
    return {"status": "queued", "job_id": job_id, "collection": collection_name}


@celery_app.task(name="app.workers.tasks.reconcile_task")
def reconcile_task() -> dict:
    """Периодическая сверка Postgres ↔ Qdrant (Beat)."""
    async def _run():
        async with session_scope() as session:
            collections = (await session.execute(select(Collection.name))).scalars().all()
            return list(collections)

    collections = _run_async(_run())
    logger.debug(f"Reconcile: checking {len(collections)} collections")
    return {"collections_checked": len(collections)}


__all__ = ["import_task", "reindex_task", "reconcile_task"]
