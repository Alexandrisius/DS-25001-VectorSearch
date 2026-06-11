"""FolderService — управление папками (категориями) иерархии."""
from __future__ import annotations

import uuid as uuid_mod
from typing import Any
from uuid import UUID

from loguru import logger
from qdrant_client.http import models as qm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.qdrant import get_qdrant_client
from app.models.collection import Collection
from app.models.folder import Folder
from app.utils.path_levels import build_full_path, extract_folders_from_records


def deterministic_folder_uuid(full_path: str) -> UUID:
    code = f"folder::{full_path.replace(' → ', '::')}"
    return UUID(str(uuid_mod.uuid5(uuid_mod.NAMESPACE_DNS, code)))


class FolderService:
    """Управление папками: извлечение, синхронизация, orphan-detection."""

    def __init__(self, session: AsyncSession, embedding_service=None) -> None:
        self.session = session
        self.embedding_service = embedding_service

    @property
    def qdrant(self):
        return get_qdrant_client()

    # -------------------------------------------------------------- extract
    def extract_from_records(
        self, records: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Извлечь уникальные папки из path_levels записей."""
        return extract_folders_from_records(records)

    # ---------------------------------------------------------- rebuild all
    async def rebuild_for_collection(
        self,
        collection: Collection,
        records: list[dict[str, Any]],
        *,
        progress_cb=None,
    ) -> dict[str, int]:
        """Полная пересборка папок для коллекции.

        1. Извлечь уникальные папки из records.
        2. Upsert в Postgres (по full_path).
        3. Генерировать эмбеддинги + upsert в Qdrant (is_folder=true).
        4. Удалить осиротевшие папки (те, которых больше нет в records).
        """
        new_folders = self.extract_from_records(records)
        new_paths = {f["full_path"] for f in new_folders}

        # Текущие папки в БД
        result = await self.session.execute(
            select(Folder).where(Folder.collection_id == collection.id)
        )
        existing = {f.full_path: f for f in result.scalars().all()}

        # Удалить осиротевшие
        deleted = 0
        for old_path, old_folder in list(existing.items()):
            if old_path not in new_paths:
                try:
                    self.qdrant.delete(collection.name, [old_folder.qdrant_point_id])
                except Exception:
                    pass
                await self.session.delete(old_folder)
                deleted += 1
        await self.session.flush()

        # Upsert новых
        created = 0
        updated = 0
        for f_data in new_folders:
            full_path = f_data["full_path"]
            folder_id = deterministic_folder_uuid(full_path)

            # Embedding
            if self.embedding_service is None:
                raise RuntimeError("EmbeddingService не передан в FolderService")
            vector = await self.embedding_service.embed_one(full_path)

            payload = {
                "code": f"folder::{full_path.replace(' → ', '::')}",
                "description": full_path,
                "full_path": full_path,
                "leaf_name": f_data["leaf_name"],
                "path_depth": f_data["level"],
                "items_count": f_data["items_count"],
                "is_folder": True,
                **f_data["path_levels"],
            }

            # Upsert в Qdrant
            self.qdrant.upsert(
                collection.name,
                [qm.PointStruct(id=folder_id, vector=vector, payload=payload)],
            )

            # Upsert в Postgres
            existing_f = existing.get(full_path)
            if existing_f:
                existing_f.leaf_name = f_data["leaf_name"]
                existing_f.level = f_data["level"]
                existing_f.items_count = f_data["items_count"]
                existing_f.qdrant_point_id = folder_id
                updated += 1
            else:
                self.session.add(
                    Folder(
                        collection_id=collection.id,
                        full_path=full_path,
                        leaf_name=f_data["leaf_name"],
                        parent_id=None,  # TODO: вычислить по parent_path
                        level=f_data["level"],
                        items_count=f_data["items_count"],
                        qdrant_point_id=folder_id,
                    )
                )
                created += 1
            if progress_cb:
                progress_cb()

        await self.session.flush()
        logger.info(
            f"📁 Folders rebuilt: {created} created, {updated} updated, {deleted} deleted"
        )
        return {"created": created, "updated": updated, "deleted": deleted}

    # ----------------------------------------------------- orphan detection
    async def check_orphans_after_delete(
        self, collection: Collection, deleted_material: Any
    ) -> list[str]:
        """Проверить и удалить осиротевшие папки после удаления материала.

        deleted_material должен иметь folder_ids (list[UUID]) и path_levels.
        """
        folder_ids = (deleted_material.payload or {}).get("folder_ids", []) if deleted_material.payload else []
        path_levels = deleted_material.path_levels or {}
        depth = path_levels.get("path_depth", 0)

        if depth == 0:
            return []

        # Собираем пути от самого глубокого к корневому
        paths: list[str] = []
        parts: list[str] = []
        for i in range(1, depth + 1):
            v = path_levels.get(f"path_level_{i}")
            if v:
                parts.append(v)
                paths.append(" → ".join(parts))

        deleted_paths: list[str] = []
        for path in reversed(paths):
            # Проверяем, остались ли материалы с таким путём
            conditions = []
            for i, part in enumerate(path.split(" → ")):
                conditions.append(
                    qm.FieldCondition(
                        key=f"path_level_{i + 1}",
                        match=qm.MatchValue(value=part),
                    )
                )
            try:
                count = self.qdrant.count(
                    collection_name=collection.name,
                    count_filter=qm.Filter(
                        must=conditions,
                        must_not=[
                            qm.FieldCondition(
                                key="is_folder", match=qm.MatchValue(value=True)
                            )
                        ],
                    ),
                ).count
            except Exception as e:
                logger.warning(f"Не удалось подсчитать материалы в '{path}': {e}")
                count = 1

            if count == 0:
                # Папка осиротела — удалить
                folder_code = f"folder::{path.replace(' → ', '::')}"
                folder_uuid = UUID(str(uuid_mod.uuid5(uuid_mod.NAMESPACE_DNS, folder_code)))
                try:
                    self.qdrant.delete(collection.name, [folder_uuid])
                except Exception:
                    pass
                # Удалить из Postgres
                result = await self.session.execute(
                    select(Folder).where(
                        Folder.collection_id == collection.id,
                        Folder.full_path == path,
                    )
                )
                f_db = result.scalar_one_or_none()
                if f_db:
                    await self.session.delete(f_db)
                deleted_paths.append(path)
            else:
                break
        await self.session.flush()
        return deleted_paths


__all__ = ["FolderService", "deterministic_folder_uuid"]
