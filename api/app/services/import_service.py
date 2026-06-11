"""ImportService — массовый импорт Excel/CSV с генерацией эмбеддингов + folders."""
from __future__ import annotations

import asyncio
import json
import uuid as uuid_mod
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from loguru import logger
from qdrant_client.http import models as qm
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.db.qdrant import get_qdrant_client
from app.models.background_job import BackgroundJob, JobStatus
from app.models.collection import Collection
from app.models.material import Material
from app.services.cleaning_runner import CleaningRunner
from app.services.embedding_service import EmbeddingService
from app.utils.path_levels import build_full_path, generate_path_levels
from app.workers.job_events import publish_job_progress


def deterministic_uuid(code: str) -> UUID:
    return UUID(str(uuid_mod.uuid5(uuid_mod.NAMESPACE_DNS, code)))


def deterministic_folder_uuid(full_path: str) -> UUID:
    code = f"folder::{full_path.replace(' → ', '::')}"
    return UUID(str(uuid_mod.uuid5(uuid_mod.NAMESPACE_DNS, code)))


def apply_column_mapping(
    records: list[dict[str, Any]],
    column_mapping: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Применить маппинг колонок Excel → стандартные поля записи.

    column_mapping: {
        "code": ["Код КСР", "Номер материала ЕХ"],
        "description": ["Наименование ресурсов ЕХ"],
        "hierarchy": ["Раздел", "Группа", "Книга", "Часть", "Статья"],
        "code_separator": ".",
        "description_separator": " ",
    }

    Возвращает [{code, description, hierarchy?, meta}] — готово для import_records.
    Записи с пустым code или description отбрасываются.
    Если column_mapping is None — записи проходят as-is (для обратной совместимости).
    """
    if not column_mapping:
        return records

    code_cols: list[str] = column_mapping.get("code") or []
    desc_cols: list[str] = column_mapping.get("description") or []
    hierarchy_cols: list[str] = column_mapping.get("hierarchy") or []
    code_sep: str = column_mapping.get("code_separator") or "."
    desc_sep: str = column_mapping.get("description_separator") or " "

    if not code_cols or not desc_cols:
        logger.warning(
            f"[column_mapping] no code/description columns specified "
            f"(code_cols={code_cols}, desc_cols={desc_cols}) — skip mapping"
        )
        return records

    logger.info(
        f"[column_mapping] applying: code={code_cols} desc={desc_cols} hierarchy={hierarchy_cols} "
        f"code_sep={code_sep!r} desc_sep={desc_sep!r}"
    )

    mapped: list[dict[str, Any]] = []
    skipped = 0
    for rec in records:
        def parts(cols: list[str]) -> list[str]:
            return [str(rec.get(c, "")).strip() for c in cols if str(rec.get(c, "")).strip()]

        code = code_sep.join(parts(code_cols))
        description = desc_sep.join(parts(desc_cols))
        if not code or not description:
            skipped += 1
            continue
        hierarchy = None
        if hierarchy_cols:
            hierarchy_parts = parts(hierarchy_cols)
            if hierarchy_parts:
                hierarchy = " → ".join(hierarchy_parts)
        mapped.append(
            {
                "code": code,
                "description": description,
                "hierarchy": hierarchy,
                "meta": rec,
            }
        )
    logger.info(f"[column_mapping] done: {len(mapped)} mapped, {skipped} skipped (empty code/desc)")
    return mapped


class ImportService:
    """Импорт данных в коллекцию.

    Алгоритм:
    1. Получить записи.
    2. Применить cleaning_rules.
    3. Сгенерировать path_levels для каждой записи.
    4. Батч-эмбеддинг (OpenRouter / локально).
    5. Upsert в Postgres (batch, ON CONFLICT).
    6. Upsert в Qdrant (batch).
    7. Пересобрать папки (extract + upsert в Postgres + Qdrant).
    """

    def __init__(
        self,
        session: AsyncSession,
        embedding_service: EmbeddingService,
        cleaning: CleaningRunner,
    ) -> None:
        self.session = session
        self.embedding = embedding_service
        self.cleaning = cleaning

    @property
    def qdrant(self):
        return get_qdrant_client()

    # ------------------------------------------------------------------
    # Main entry — chunked pipeline (вызывается из Celery worker)
    # ------------------------------------------------------------------
    async def import_records(
        self,
        collection: Collection,
        records: list[dict[str, Any]],
        job: BackgroundJob | None = None,
        batch_size: int | None = None,  # None → use self.embedding.batch_size
    ) -> dict[str, Any]:
        """Импортировать записи chunked pipeline.

        Архитектура (best practices из exa):
        1. Pre-process: cleaning + path_levels (быстро, в RAM)
        2. Для каждого chunk (по умолчанию 200):
           - embed_batch(chunk) — embeddings только для chunk (memory bounded)
           - bulk pg_insert(chunk) — Postgres batch insert
           - qdrant.upsert(chunk) — Qdrant batch upsert
           - commit + publish progress
        3. После всех чанков: rebuild_folders (нужны ВСЕ path_levels)

        Преимущества:
        - Memory bounded: RAM = batch_size * 4096d * 4 bytes = ~3 MB
        - Прерывание: N чанков уже в БД
        - Backpressure: если upsert медленный, embed не flood'ит
        - Bulk insert: 5-10x быстрее row-by-row
        """
        import time as _time
        total = len(records)
        logger.info(
            f"[import] START collection={collection.name!r} job={job.id if job else None} "
            f"total={total} batch_size={batch_size}"
        )
        # Если batch_size не передан — берём из EmbeddingService (настройки провайдера)
        if batch_size is None:
            batch_size = self.embedding.batch_size
            logger.info(f"[import] using provider batch_size={batch_size}")
        if records:
            first = records[0]
            logger.info(f"[import] first_record_keys={list(first.keys())}")

        if job:
            job.total = total
            job.status = JobStatus.PROCESSING.value
            job.started_at = datetime.now(timezone.utc)
            await self.session.flush()

        # 1. Pre-process: cleaning + path_levels (pass 1, быстро)
        cleaning_rules = await self.cleaning.load_rules()
        processed: list[dict[str, Any]] = []
        all_path_levels: list[dict[str, Any]] = []
        skipped_empty = 0

        for idx, rec in enumerate(records):
            code = str(rec.get("code", "")).strip()
            description = str(rec.get("description", "")).strip()
            hierarchy = rec.get("hierarchy")
            if not code or not description:
                skipped_empty += 1
                continue

            if hierarchy:
                hierarchy = self.cleaning.apply(hierarchy, "hierarchy", cleaning_rules)

            path_levels = generate_path_levels(description, hierarchy=hierarchy)
            for k, v in list(path_levels.items()):
                if k.startswith("path_level_") and isinstance(v, str):
                    path_levels[k] = self.cleaning.apply(v, "hierarchy", cleaning_rules).strip()

            processed.append({
                "code": code,
                "description": description,
                "context": path_levels.get("context_description", description),
                "path_levels": path_levels,
                "meta": rec.get("meta", {}),
            })
            all_path_levels.append(path_levels)

        logger.info(f"[import] preprocessing done: processed={len(processed)}/{total}, skipped_empty={skipped_empty}")

        if job:
            job.details = f"Обработка {len(processed)}/{total} записей (chunked pipeline)…"
            job.progress = 5
            await self.session.flush()
            publish_job_progress(str(job.id), {
                "type": "progress",
                "data": {"status": "processing", "progress": 5, "details": job.details},
            })

        # 2-4. CHUNKED PIPELINE
        # НЕ делаем pre-delete через MatchAny (для 142k кодов payload = 90 MB
        # > 32 MB Qdrant лимит). Qdrant upsert идемпотентен по point ID —
        # deterministic_uuid(code) всегда одинаков, upsert перезапишет
        # существующую точку. Так что удалять заранее не нужно.

        # Process in chunks
        total_chunks = (len(processed) + batch_size - 1) // batch_size
        last_progress_publish = 0.0
        imported_count = 0
        start_time = _time.monotonic()

        for chunk_idx in range(total_chunks):
            chunk_start = chunk_idx * batch_size
            chunk_end = min(chunk_start + batch_size, len(processed))
            chunk = processed[chunk_start:chunk_end]
            chunk_texts = [p["context"] for p in chunk]

            # 2. Embed только для chunk (memory bounded)
            try:
                chunk_embeddings = await self.embedding.embed_batch(chunk_texts)
            except Exception as e:
                logger.error(f"[import] chunk {chunk_idx+1}/{total_chunks} embed FAILED: {e}")
                raise

            # 3. Bulk pg_insert
            await self._upsert_materials_bulk(collection, chunk, chunk_embeddings)

            # 4. Qdrant batch upsert
            await self._upsert_to_qdrant_chunk(collection, chunk, chunk_embeddings)

            # Commit транзакцию (если упадём — этот чанк уже в БД)
            try:
                await self.session.commit()
            except Exception as e:
                logger.error(f"[import] chunk {chunk_idx+1} commit failed: {e}")
                await self.session.rollback()
                raise

            imported_count += len(chunk)

            # Progress (с throttling 1 раз в 500мс)
            now = _time.monotonic()
            pct = 5 + int((chunk_idx + 1) / total_chunks * 85)  # 5% -> 90%
            if job:
                job.progress = pct
                elapsed = now - start_time
                rate = imported_count / max(elapsed, 0.1)
                job.details = f"Импорт: {imported_count}/{len(processed)} ({pct}%)"
                await self.session.flush()

            # Обновляем last_updated каждые 10 чанков (≈10k записей),
            # чтобы UI видел актуальную дату в процессе импорта.
            if (chunk_idx + 1) % 10 == 0:
                collection.last_updated = datetime.now(timezone.utc).date()

            if (now - last_progress_publish) > 0.5 or (chunk_idx + 1) == total_chunks:
                publish_job_progress(str(job.id) if job else "", {
                    "type": "progress",
                    "data": {
                        "status": "processing",
                        "progress": pct,
                        "details": f"Импорт: {imported_count}/{len(processed)} записей"
                                 + (f" ({rate:.0f}/sec)" if job and rate > 0 else ""),
                    },
                })
                last_progress_publish = now
                logger.info(
                    f"[import] chunk {chunk_idx+1}/{total_chunks} done: "
                    f"{imported_count}/{len(processed)} records"
                )

        # 5. Пересобрать папки (нужны все path_levels)
        if job:
            job.details = "Пересборка папок…"
            job.progress = 92
            await self.session.flush()
            publish_job_progress(str(job.id), {
                "type": "progress",
                "data": {"status": "processing", "progress": 92, "details": "Пересборка папок…"},
            })

        folder_stats = await self._rebuild_folders(collection, all_path_levels)

        # 6. Удалить папки по списку (если передан)
        folders_to_delete = []
        if job and job.params:
            folders_to_delete = job.params.get("folders_to_delete", [])

        if folders_to_delete:
            if job:
                job.details = f"Удаление {len(folders_to_delete)} папок…"
                await self.session.flush()
            for fp in folders_to_delete:
                fid = deterministic_folder_uuid(fp)
                try:
                    self.qdrant.delete(collection.name, [fid])
                except Exception:
                    pass
            folder_stats["deleted_by_request"] = len(folders_to_delete)

        # 7. Финал
        collection.last_updated = datetime.now(timezone.utc).date()
        if job:
            job.progress = 100
            job.status = JobStatus.COMPLETED.value
            job.finished_at = datetime.now(timezone.utc)
            job.details = (
                f"Импортировано {imported_count} материалов, "
                f"папок: {folder_stats['created']} новых / {folder_stats['updated']} обновлённых / {folder_stats['deleted']} удалённых"
            )
            job.result = {
                "materials": imported_count,
                "folders": folder_stats,
            }
            await self.session.commit()
            publish_job_progress(str(job.id), {
                "type": "done",
                "data": {
                    "id": str(job.id),
                    "status": "completed",
                    "progress": 100,
                    "result": job.result,
                    "details": job.details,
                },
            })

        return {"materials": imported_count, "folders": folder_stats}

    async def _flush_embed_progress(self, job_id: str, pct: int, details: str) -> None:
        """Сбросить прогресс эмбеддинга в БД + Redis pub/sub.

        Вызывается из sync callback (progress_cb) через loop.create_task.
        Не падает при ошибках — best effort.
        """
        try:
            await self.session.flush()
        except Exception:
            pass
        try:
            from app.workers.job_events import publish_job_progress
            publish_job_progress(job_id, {
                "type": "progress",
                "data": {"status": "processing", "progress": pct, "details": details},
            })
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    async def _upsert_material(
        self, collection: Collection, p: dict[str, Any], emb: list[float]
    ) -> None:
        code = p["code"]
        path_levels = p["path_levels"]
        full_path = build_full_path(path_levels)
        point_id = deterministic_uuid(code)

        stmt = pg_insert(Material).values(
            code=code,
            collection_id=collection.id,
            description=p["description"],
            full_description=path_levels.get("full_description"),
            context_description=p["context"],
            path_levels=path_levels,
            path_depth=path_levels.get("path_depth", 0),
            payload={**p["meta"], "full_path": full_path} if full_path else p["meta"],
            qdrant_point_id=point_id,
            status_id="active",
            version=1,
        )
        stmt = stmt.on_conflict_do_update(
            constraint="uq_materials_collection_code",
            set_={
                "description": stmt.excluded.description,
                "full_description": stmt.excluded.full_description,
                "context_description": stmt.excluded.context_description,
                "path_levels": stmt.excluded.path_levels,
                "path_depth": stmt.excluded.path_depth,
                "payload": stmt.excluded.payload,
                "qdrant_point_id": stmt.excluded.qdrant_point_id,
                "updated_at": datetime.now(timezone.utc),
            },
        )
        await self.session.execute(stmt)
        await self.session.flush()

    async def _upsert_materials_bulk(
        self,
        collection: Collection,
        chunk: list[dict[str, Any]],
        embeddings: list[list[float]],
    ) -> None:
        """Bulk upsert в Postgres: один INSERT с VALUES (...), (...), ...

        По best practices из exa: 5-10K row chunks, batch payload.
        Здесь 200 — оптимально для Qdrant batch.
        """
        if not chunk:
            return
        now = datetime.now(timezone.utc)
        values_list = []
        for p, emb in zip(chunk, embeddings):
            path_levels = p["path_levels"]
            full_path = build_full_path(path_levels)
            values_list.append({
                "code": p["code"],
                "collection_id": collection.id,
                "description": p["description"],
                "full_description": path_levels.get("full_description"),
                "context_description": p["context"],
                "path_levels": path_levels,
                "path_depth": path_levels.get("path_depth", 0),
                "payload": {**p["meta"], "full_path": full_path} if full_path else p["meta"],
                "qdrant_point_id": deterministic_uuid(p["code"]),
                "status_id": "active",
                "version": 1,
                "created_at": now,
                "updated_at": now,
            })

        stmt = pg_insert(Material).values(values_list)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_materials_collection_code",
            set_={
                "description": stmt.excluded.description,
                "full_description": stmt.excluded.full_description,
                "context_description": stmt.excluded.context_description,
                "path_levels": stmt.excluded.path_levels,
                "path_depth": stmt.excluded.path_depth,
                "payload": stmt.excluded.payload,
                "qdrant_point_id": stmt.excluded.qdrant_point_id,
                "updated_at": stmt.excluded.updated_at,
            },
        )
        await self.session.execute(stmt)

    async def _upsert_to_qdrant_chunk(
        self,
        collection: Collection,
        chunk: list[dict[str, Any]],
        embeddings: list[list[float]],
    ) -> None:
        """Qdrant batch upsert через gRPC (обходит 32 MB HTTP лимит)."""
        if not chunk:
            return
        points = []
        for p, emb in zip(chunk, embeddings):
            payload = {
                "code": p["code"],
                "description": p["description"],
                "full_description": p["path_levels"].get("full_description"),
                "context_description": p["context"],
                "path_depth": p["path_levels"].get("path_depth", 0),
                "is_folder": False,
            }
            full_path = build_full_path(p["path_levels"])
            if full_path:
                payload["full_path"] = full_path
            payload.update({k: v for k, v in p["path_levels"].items() if k.startswith("path_level_")})
            payload.update(p["meta"])
            points.append(
                qm.PointStruct(
                    id=deterministic_uuid(p["code"]),
                    vector=emb,
                    payload=payload,
                )
            )

        # Оценка размера для логирования (Qdrant использует gRPC, лимит 100 MB)
        approx_size_bytes = sum(
            len(p.payload.get("description", "")) +
            len(p.payload.get("full_description") or "") +
            len(p.payload.get("context_description", "")) +
            len(p.payload.get("full_path", "")) +
            sum(len(v) for k, v in p.payload.items() if k.startswith("path_level_"))
            for p in points
        ) + len(points) * 4096 * 4  # vectors binary
        approx_size_mb = approx_size_bytes / 1024 / 1024
        logger.info(f"[qdrant] upsert via gRPC: {len(points)} points, ~{approx_size_mb:.1f} MB")

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None, lambda: self.qdrant.upsert(collection.name, points=points)
        )

    async def _upsert_to_qdrant(
        self,
        collection: Collection,
        processed: list[dict[str, Any]],
        embeddings: list[list[float]],
    ) -> None:
        # Сначала удалить все записи с этими кодами (для устранения дубликатов)
        codes = [p["code"] for p in processed]
        self.qdrant.delete(
            collection_name=collection.name,
            points_selector=qm.Filter(
                must=[qm.FieldCondition(key="code", match=qm.MatchAny(any=codes))]
            ),
        )

        points = []
        for p, emb in zip(processed, embeddings):
            payload = {
                "code": p["code"],
                "description": p["description"],
                "full_description": p["path_levels"].get("full_description"),
                "context_description": p["context"],
                "path_depth": p["path_levels"].get("path_depth", 0),
                "is_folder": False,
            }
            full_path = build_full_path(p["path_levels"])
            if full_path:
                payload["full_path"] = full_path
            payload.update({k: v for k, v in p["path_levels"].items() if k.startswith("path_level_")})
            payload.update(p["meta"])
            points.append(
                qm.PointStruct(
                    id=deterministic_uuid(p["code"]),
                    vector=emb,
                    payload=payload,
                )
            )
        if points:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None, lambda: self.qdrant.upsert(collection.name, points=points)
            )

    async def _rebuild_folders(
        self, collection: Collection, all_path_levels: list[dict[str, Any]]
    ) -> dict[str, int]:
        """Пересобрать папки (extract + upsert в Postgres + Qdrant)."""
        from app.utils.path_levels import extract_folders_from_records

        new_folders = extract_folders_from_records(all_path_levels)
        new_paths = {f["full_path"] for f in new_folders}

        # Текущие папки
        result = await self.session.execute(
            select(Material).where(  # type: ignore[arg-type]
                Material.collection_id == collection.id,
            )
        )
        # Удалить осиротевшие
        deleted = 0
        # (Простая версия: ищем в Qdrant, чего больше нет в new_paths)
        loop = asyncio.get_event_loop()

        def _scroll_existing():
            offset = None
            existing_paths: dict[str, str] = {}  # full_path -> qdrant_point_id
            while True:
                points, offset = self.qdrant.scroll(
                    collection_name=collection.name,
                    limit=2000,
                    offset=offset,
                    with_payload=["full_path", "leaf_name"],
                    with_vectors=False,
                    scroll_filter=qm.Filter(
                        must=[
                            qm.FieldCondition(
                                key="is_folder", match=qm.MatchValue(value=True)
                            )
                        ]
                    ),
                )
                for p in points:
                    fp = (p.payload or {}).get("full_path", "")
                    if fp and fp not in new_paths:
                        existing_paths[fp] = str(p.id)
                if offset is None:
                    break
            return existing_paths

        try:
            existing_orphans = await loop.run_in_executor(None, _scroll_existing)
            for fp, pid in existing_orphans.items():
                try:
                    self.qdrant.delete(collection.name, [pid])
                except Exception:
                    pass
                deleted += 1
        except Exception as e:
            logger.warning(f"Не удалось просканировать старые папки: {e}")

        # Upsert новых
        created = 0
        for f in new_folders:
            fp = f["full_path"]
            fid = deterministic_folder_uuid(fp)
            vector = await self.embedding.embed_one(fp)
            payload = {
                "code": f"folder::{fp.replace(' → ', '::')}",
                "description": fp,
                "full_path": fp,
                "leaf_name": f["leaf_name"],
                "path_depth": f["level"],
                "items_count": f["items_count"],
                "is_folder": True,
                **{k: v for k, v in f["path_levels"].items() if k.startswith("path_level_")},
            }
            self.qdrant.upsert(
                collection.name,
                [qm.PointStruct(id=fid, vector=vector, payload=payload)],
            )
            created += 1

        return {"created": created, "updated": 0, "deleted": deleted}


__all__ = ["ImportService"]
