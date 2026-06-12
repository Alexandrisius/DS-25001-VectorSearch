"""MaterialService — CRUD материалов + генерация path_levels + sync с Qdrant."""
from __future__ import annotations

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
from app.models.collection import Collection
from app.models.material import Material
from app.utils.path_levels import build_full_path, generate_path_levels


def deterministic_uuid(code: str) -> UUID:
    return UUID(str(uuid_mod.uuid5(uuid_mod.NAMESPACE_DNS, code)))


class MaterialService:
    """CRUD материалов. Postgres = SoT, Qdrant = vector index."""

    def __init__(
        self,
        session: AsyncSession,
        embedding_service=None,
    ) -> None:
        self.session = session
        self.embedding_service = embedding_service

    @property
    def qdrant(self):
        return get_qdrant_client()

    # ------------------------------------------------------------------ read
    async def get_by_id(self, material_id: int) -> Material | None:
        return await self.session.get(Material, material_id)

    async def get_by_code(self, collection_id: int, code: str) -> Material | None:
        result = await self.session.execute(
            select(Material).where(
                Material.collection_id == collection_id,
                Material.code == code,
            )
        )
        return result.scalars().first()

    async def get_by_qdrant_id(self, point_id: UUID) -> Material | None:
        result = await self.session.execute(
            select(Material).where(Material.qdrant_point_id == point_id)
        )
        return result.scalars().first()

    # --------------------------------------------------------------- create
    async def upsert(
        self,
        collection: Collection,
        code: str,
        description: str,
        *,
        hierarchy: str | None = None,
        meta: dict[str, Any] | None = None,
        status_id: str = "active",
    ) -> Material:
        """Создать или обновить материал (Postgres + Qdrant)."""
        path_levels = generate_path_levels(description, hierarchy=hierarchy)
        full_path = build_full_path(path_levels)
        context = path_levels.get("context_description", description)
        point_id = deterministic_uuid(code)

        if self.embedding_service is None:
            raise RuntimeError("EmbeddingService не передан в MaterialService")
        vector = await self.embedding_service.embed_one(context)

        # Upsert в Postgres (ON CONFLICT UPDATE)
        stmt = pg_insert(Material).values(
            code=code,
            collection_id=collection.id,
            description=description,
            full_description=path_levels.get("full_description"),
            context_description=context,
            path_levels=path_levels,
            path_depth=path_levels.get("path_depth", 0),
            payload={**(meta or {}), "full_path": full_path} if full_path else (meta or {}),
            qdrant_point_id=point_id,
            status_id=status_id,
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
                "status_id": stmt.excluded.status_id,
                "updated_at": datetime.now(timezone.utc),
            },
        )
        await self.session.execute(stmt)
        await self.session.flush()

        material = await self.get_by_code(collection.id, code)
        if not material:
            raise RuntimeError(f"Не удалось получить материал после upsert: {code}")

        # Upsert в Qdrant
        payload = material.to_payload_dict()
        if meta:
            payload.update(meta)
        self.qdrant.upsert(
            collection_name=collection.name,
            points=[
                qm.PointStruct(id=point_id, vector=vector, payload=payload)
            ],
        )
        return material

    # ---------------------------------------------------------------- edit
    async def update_cell(
        self,
        material: Material,
        collection: Collection,
        field: str,
        value: str,
    ) -> Material:
        """Изменить одно поле материала (inline edit)."""
        point_id = material.qdrant_point_id
        path_levels = dict(material.path_levels or {})

        need_reembed = False

        if field == "description":
            # Legacy: меняется полное описание
            new_path_levels = generate_path_levels(value, separator="→")
            path_levels = new_path_levels
            material.description = value
            material.full_description = new_path_levels.get("full_description")
            material.context_description = new_path_levels.get("context_description")
            material.path_depth = new_path_levels.get("path_depth", 0)
            need_reembed = True
        elif field == "full_description":
            material.full_description = value
            new_path_levels = dict(path_levels)
            new_path_levels["full_description"] = value
            new_ctx = _rebuild_context_description(new_path_levels)
            material.context_description = new_ctx
            material.description = new_ctx
            path_levels = new_path_levels
            need_reembed = True
        elif field.startswith("path_level_"):
            level_num = int(field.split("_")[-1])
            path_levels[field] = value
            current_depth = material.path_depth or 0
            if level_num > current_depth:
                material.path_depth = level_num
            new_ctx = _rebuild_context_description(path_levels)
            material.context_description = new_ctx
            material.description = new_ctx
            need_reembed = True
        elif field == "code":
            # Удалить старый и вставить новый
            old_point_id = point_id
            new_point_id = deterministic_uuid(value)
            # Удалить старый
            self.qdrant.delete(collection.name, [old_point_id])
            # Upsert новый
            material.code = value
            material.qdrant_point_id = new_point_id
            vector = await self._get_vector(material)
            self.qdrant.upsert(
                collection.name,
                [qm.PointStruct(id=new_point_id, vector=vector, payload=material.to_payload_dict())],
            )
        elif field == "status":
            material.status_id = value
        else:
            # Произвольное поле
            if material.payload is None:
                material.payload = {}
            material.payload[field] = value

        material.path_levels = path_levels
        material.version = (material.version or 1) + 1
        material.updated_at = datetime.now(timezone.utc)
        await self.session.flush()

        if need_reembed:
            vector = await self._get_vector(material)
            self.qdrant.upsert(
                collection.name,
                [
                    qm.PointStruct(
                        id=point_id,
                        vector=vector,
                        payload=material.to_payload_dict(),
                    )
                ],
            )

        return material

    # -------------------------------------------------------------- delete
    async def delete(self, material: Material, collection: Collection) -> None:
        """Удалить материал + связанные осиротевшие папки."""
        self.qdrant.delete(collection.name, [material.qdrant_point_id])
        await self.session.delete(material)
        await self.session.flush()

    # -------------------------------------------------------------- helpers
    async def _get_vector(self, material: Material) -> list[float]:
        if self.embedding_service is None:
            raise RuntimeError("EmbeddingService не передан")
        return await self.embedding_service.embed_one(
            material.context_description or material.description or material.code
        )


def _rebuild_context_description(path_levels: dict[str, Any]) -> str:
    depth = path_levels.get("path_depth", 0)
    full = path_levels.get("full_description", "")
    parts: list[str] = []
    for i in range(1, depth + 1):
        v = path_levels.get(f"path_level_{i}")
        if v:
            parts.append(v)
    if parts and full:
        return " → ".join(parts + [full])
    if parts:
        return " → ".join(parts)
    return full


__all__ = ["MaterialService", "deterministic_uuid", "_rebuild_context_description"]
