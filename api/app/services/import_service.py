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


def deterministic_uuid(code: str) -> UUID:
    return UUID(str(uuid_mod.uuid5(uuid_mod.NAMESPACE_DNS, code)))


def deterministic_folder_uuid(full_path: str) -> UUID:
    code = f"folder::{full_path.replace(' → ', '::')}"
    return UUID(str(uuid_mod.uuid5(uuid_mod.NAMESPACE_DNS, code)))


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
    # Main entry — синхронный (вызывается из Celery worker)
    # ------------------------------------------------------------------
    async def import_records(
        self,
        collection: Collection,
        records: list[dict[str, Any]],
        job: BackgroundJob | None = None,
        batch_size: int = 32,
    ) -> dict[str, Any]:
        """Импортировать записи (sync, вызывается из Celery)."""
        total = len(records)
        if job:
            job.total = total
            job.status = JobStatus.PROCESSING.value
            job.started_at = datetime.now(timezone.utc)
            await self.session.flush()

        # 1. Pre-process: cleaning + path_levels
        cleaning_rules = await self.cleaning.load_rules()
        processed: list[dict[str, Any]] = []
        all_path_levels: list[dict[str, Any]] = []

        for rec in records:
            code = str(rec.get("code", "")).strip()
            description = str(rec.get("description", "")).strip()
            hierarchy = rec.get("hierarchy")
            if not code or not description:
                continue

            if hierarchy:
                hierarchy = self.cleaning.apply(hierarchy, "hierarchy", cleaning_rules)

            path_levels = generate_path_levels(description, hierarchy=hierarchy)
            # Дополнительная очистка каждого уровня
            for k, v in list(path_levels.items()):
                if k.startswith("path_level_") and isinstance(v, str):
                    path_levels[k] = self.cleaning.apply(v, "hierarchy", cleaning_rules).strip()

            processed.append(
                {
                    "code": code,
                    "description": description,
                    "context": path_levels.get("context_description", description),
                    "path_levels": path_levels,
                    "meta": rec.get("meta", {}),
                }
            )
            all_path_levels.append(path_levels)

        if job:
            job.details = f"Обработка {len(processed)}/{total} записей…"
            await self.session.flush()

        # 2. Батч-эмбеддинг
        texts = [p["context"] for p in processed]
        embeddings: list[list[float]] = []
        chunk = max(1, batch_size)
        for i in range(0, len(texts), chunk):
            sub = texts[i : i + chunk]
            vecs = await self.embedding.embed_batch(sub)
            embeddings.extend(vecs)
            if job:
                done = min(i + chunk, len(texts))
                job.progress = int(done / max(1, total) * 80)  # 0-80% на эмбеддинги
                job.details = f"Эмбеддинги: {done}/{len(texts)}"
                await self.session.flush()

        # 3. Upsert в Postgres
        if job:
            job.details = "Upsert в Postgres…"
            job.progress = 80
            await self.session.flush()

        for p, emb in zip(processed, embeddings):
            await self._upsert_material(collection, p, emb)

        # 4. Upsert в Qdrant (батч)
        if job:
            job.details = "Upsert в Qdrant…"
            await self.session.flush()

        await self._upsert_to_qdrant(collection, processed, embeddings)

        # 5. Пересобрать папки
        if job:
            job.details = "Пересборка папок…"
            job.progress = 90
            await self.session.flush()

        folder_stats = await self._rebuild_folders(collection, all_path_levels)

        # 6. Финал
        collection.last_updated = datetime.now(timezone.utc).date()
        if job:
            job.progress = 100
            job.status = JobStatus.COMPLETED.value
            job.finished_at = datetime.now(timezone.utc)
            job.details = (
                f"Импортировано {len(processed)} материалов, "
                f"папок: {folder_stats['created']} новых / {folder_stats['updated']} обновлённых / {folder_stats['deleted']} удалённых"
            )
            job.result = {
                "materials": len(processed),
                "folders": folder_stats,
            }
            await self.session.flush()

        return {"materials": len(processed), "folders": folder_stats}

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
