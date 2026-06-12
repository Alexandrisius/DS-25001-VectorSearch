"""Celery tasks — реальная логика."""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from loguru import logger
from sqlalchemy import update

from app.cache.excel_cache import delete_excel_from_cache, load_excel_from_cache
from app.db.postgres import session_scope
from app.models.background_job import BackgroundJob, JobStatus
from app.models.collection import Collection
from app.services.cleaning_runner import CleaningRunner
from app.services.embedding_service import EmbeddingService
from app.services.import_service import ImportService
from app.services.settings_service import SettingsService
from app.workers.celery_app import celery_app


def _run_async(coro):
    """Запустить async корутину из синхронного контекста Celery worker.

    Celery worker использует свой event loop для prefork, и asyncio.run()
    может конфликтовать с ним. Создаём новый loop вручную.
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError("loop is closed")
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


@celery_app.task(name="app.workers.tasks.import_task", bind=True)
def import_task(
    self,
    job_id: str,
    collection_id: int,
    cache_key: str | None = None,
    records: list[dict] | None = None,
    column_mapping: dict | None = None,
) -> dict:
    """Массовый импорт (вызывается из API).

    Передаётся либо cache_key (тогда данные читаются из Redis), либо records
    напрямую. cache_key предпочтительнее для больших файлов (>10k строк)
    чтобы не класть 28 MB JSON в Redis message queue.

    column_mapping — маппинг колонок Excel → поля (если не указан, записи
    должны уже иметь ключи code/description/hierarchy).
    """
    logger.info(f"[import_task] START job_id={job_id} collection_id={collection_id} cache_key={cache_key!r} has_records={records is not None} has_mapping={column_mapping is not None}")
    # Получаем записи
    if cache_key:
        # В worker — синхронный контекст, используем _run_async
        cached = _run_async(load_excel_from_cache(cache_key))
        if not cached:
            raise ValueError(
                f"Cache '{cache_key}' не найден или истёк. "
                f"Загрузите Excel заново."
            )
        records = cached.get("data", [])
        logger.info(f"[import_task] Loaded {len(records)} records from Redis cache '{cache_key}'")
    elif records is None:
        records = []
    logger.info(f"[import_task] Import job {job_id}: {len(records)} records for coll {collection_id}")
    if records:
        first_keys = list(records[0].keys())
        logger.info(f"[import_task] first record keys: {first_keys}")
        sample = {k: str(records[0].get(k, ""))[:100] for k in first_keys}
        logger.info(f"[import_task] first record sample: {json.dumps(sample, ensure_ascii=False)}")

    # Применяем column_mapping к records (если задан)
    if column_mapping and records:
        from app.services.import_service import apply_column_mapping
        before = len(records)
        records = apply_column_mapping(records, column_mapping)
        logger.info(f"[import_task] column_mapping applied: {before} -> {len(records)} records")
        if records:
            logger.info(f"[import_task] after mapping first record: {json.dumps({k: str(v)[:80] for k, v in records[0].items()}, ensure_ascii=False)}")

    async def _run():
        async with session_scope() as session:
            # Обновить статус
            await session.execute(
                update(BackgroundJob)
                .where(BackgroundJob.id == uuid.UUID(job_id))
                .values(status=JobStatus.PROCESSING.value, started_at=datetime.now(timezone.utc))
            )

            # Получить коллекцию
            coll = await session.get(Collection, collection_id)
            if not coll:
                raise ValueError(f"Коллекция {collection_id} не найдена")

            # Получить job
            from sqlalchemy import select
            res = await session.execute(
                select(BackgroundJob).where(BackgroundJob.id == uuid.UUID(job_id))
            )
            job = res.scalar_one()

            # Инициализировать сервисы
            settings_svc = SettingsService(session)
            prov = await settings_svc.get_active_provider() or await settings_svc.get_provider("openrouter")
            if not prov or not prov.api_key_encrypted:
                raise ValueError("OpenRouter не настроен")

            from app.core.security import decrypt_secret
            api_key = decrypt_secret(prov.api_key_encrypted)
            embedding = EmbeddingService(
                api_key=api_key,
                model=prov.model_embed,
                batch_size=prov.batch_size,
                max_workers=prov.max_workers,
                base_url=prov.base_url,
            )
            cleaning = CleaningRunner(session)
            import_svc = ImportService(session, embedding_service=embedding, cleaning=cleaning)

            try:
                # Outer chunk = batch_size × max_workers.
                # EmbeddingService разобьёт outer chunk на max_workers под-chunks
                # по batch_size и пошлёт их параллельно через Semaphore.
                # Пример: batch=100, workers=10 → outer=1000 за раз.
                outer_chunk = prov.batch_size * prov.max_workers
                logger.info(
                    f"[import_task] using outer_chunk={outer_chunk} "
                    f"(batch={prov.batch_size} × workers={prov.max_workers})"
                )
                result = await import_svc.import_records(
                    coll, records, job=job,
                    batch_size=outer_chunk,
                )
                # import_records сам выставляет status=COMPLETED с подробностями
                # в job.details. Не перезатираем здесь — иначе пропадёт
                # cancellation (если job был остановлен через /admin/jobs/{id}/stop)
                # и текст с количеством созданных папок/материалов.
                # Очищаем cache после успешного импорта
                if cache_key:
                    await delete_excel_from_cache(cache_key)
                return result
            except Exception as e:
                logger.exception(f"Import job {job_id} failed")
                await session.execute(
                    update(BackgroundJob)
                    .where(BackgroundJob.id == uuid.UUID(job_id))
                    .values(
                        status=JobStatus.ERROR.value,
                        finished_at=datetime.now(timezone.utc),
                        error=str(e)[:500],
                    )
                )
                raise

    return _run_async(_run())


@celery_app.task(name="app.workers.tasks.reindex_task", bind=True)
def reindex_task(self, job_id: str, collection_id: int) -> dict:
    """Переиндексация папок."""
    async def _run():
        async with session_scope() as session:
            coll = await session.get(Collection, collection_id)
            if not coll:
                raise ValueError(f"Коллекция {collection_id} не найдена")
            # Получить все материалы
            from app.models.material import Material
            from sqlalchemy import select
            result = await session.execute(
                select(Material).where(Material.collection_id == coll.id)
            )
            materials = result.scalars().all()
            path_levels = [m.path_levels or {} for m in materials]
            from app.services.folder_service import FolderService
            settings_svc = SettingsService(session)
            prov = await settings_svc.get_active_provider() or await settings_svc.get_provider("openrouter")
            if not prov or not prov.api_key_encrypted:
                raise ValueError("OpenRouter не настроен")
            from app.core.security import decrypt_secret
            api_key = decrypt_secret(prov.api_key_encrypted)
            embedding = EmbeddingService(
                api_key=api_key,
                model=prov.model_embed,
                base_url=prov.base_url,
            )
            folder_svc = FolderService(session, embedding_service=embedding)
            return await folder_svc.rebuild_for_collection(coll, path_levels)

    return _run_async(_run())


@celery_app.task(name="app.workers.tasks.reconcile_task")
def reconcile_task() -> dict:
    """Периодическая сверка Postgres ↔ Qdrant."""
    async def _run():
        async with session_scope() as session:
            from sqlalchemy import select
            cols = (await session.execute(select(Collection))).scalars().all()
            return [c.name for c in cols]
    return {"collections": _run_async(_run())}


__all__ = ["import_task", "reindex_task", "reconcile_task"]
