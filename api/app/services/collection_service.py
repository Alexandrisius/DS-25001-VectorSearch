"""CollectionService — управление коллекциями (Qdrant + Postgres)."""
from __future__ import annotations

from typing import Any

from loguru import logger
from qdrant_client.http import models as qm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.db.qdrant import get_qdrant_client
from app.models.collection import Collection
from app.services.embedding_service import EmbeddingService


class CollectionService:
    """CRUD коллекций + двусторонняя синхронизация Postgres ↔ Qdrant."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @property
    def qdrant(self):
        return get_qdrant_client()

    async def list_all(self) -> list[Collection]:
        result = await self.session.execute(select(Collection).order_by(Collection.name))
        return list(result.scalars().all())

    async def get_by_name(self, name: str) -> Collection | None:
        return await self.session.get(Collection, name=name)  # type: ignore[arg-type]

    async def get_or_404(self, name: str) -> Collection:
        coll = await self.get_by_name(name)
        if not coll:
            raise NotFoundError(f"Коллекция '{name}' не найдена")
        return coll

    async def list_visible(self) -> list[Collection]:
        result = await self.session.execute(
            select(Collection).where(Collection.visible == True).order_by(Collection.name)  # noqa: E712
        )
        return list(result.scalars().all())

    async def get_current_active(self, requested_name: str | None) -> Collection | None:
        """Получить активную (или запрошенную) коллекцию."""
        if requested_name:
            return await self.get_by_name(requested_name)
        visible = await self.list_visible()
        return visible[0] if visible else None

    async def create(
        self,
        name: str,
        description: str,
        dimension: int,
        recreate: bool = False,
    ) -> Collection:
        """Создать новую коллекцию (Qdrant + Postgres)."""
        existing = await self.get_by_name(name)
        if existing and not recreate:
            raise ConflictError(f"Коллекция '{name}' уже существует. Используйте recreate=true.")

        # Удалить из Qdrant если нужно
        try:
            self.qdrant.delete_collection(name)
            logger.info(f"Удалена существующая коллекция Qdrant: {name}")
        except Exception:
            pass

        # Создать в Qdrant
        self.qdrant.create_collection(
            collection_name=name,
            vectors_config=qm.VectorParams(size=dimension, distance=qm.Distance.COSINE),
        )
        logger.info(f"✅ Коллекция Qdrant '{name}' создана (dim={dimension})")

        # Создать/обновить в Postgres
        if existing and recreate:
            existing.dimension = dimension
            existing.description = description
            await self.session.flush()
            coll = existing
        else:
            coll = Collection(
                name=name,
                description=description,
                dimension=dimension,
                visible=True,
                locked=False,
            )
            self.session.add(coll)
            await self.session.flush()

        return coll

    async def delete(self, name: str) -> None:
        coll = await self.get_or_404(name)
        if coll.locked:
            from app.core.exceptions import ForbiddenError
            raise ForbiddenError(
                f"Коллекция '{name}' защищена от удаления. Снимите флаг locked в БД."
            )
        try:
            self.qdrant.delete_collection(name)
        except Exception as e:
            logger.warning(f"Не удалось удалить Qdrant коллекцию '{name}': {e}")
        await self.session.delete(coll)
        await self.session.flush()
        logger.info(f"🗑️ Коллекция '{name}' удалена")

    async def update_config(
        self,
        name: str,
        visible: bool | None = None,
        cosine_threshold: float | None = None,
        rerank_threshold: float | None = None,
    ) -> Collection:
        coll = await self.get_or_404(name)
        if visible is not None:
            coll.visible = visible
        if cosine_threshold is not None:
            coll.cosine_threshold = cosine_threshold
        if rerank_threshold is not None:
            coll.rerank_threshold = rerank_threshold
        await self.session.flush()
        return coll

    async def sync_dimension_from_qdrant(self, name: str) -> int:
        """Подтянуть размерность из Qdrant (если нужно)."""
        info = self.qdrant.get_collection(name)
        dim = info.config.params.vectors.size
        coll = await self.get_by_name(name)
        if coll and coll.dimension != dim:
            coll.dimension = dim
            await self.session.flush()
        return dim

    async def determine_dimension(self, provider: str | None = None) -> int:
        """Определить размерность по активному провайдеру."""
        from app.services.settings_service import SettingsService

        settings_svc = SettingsService(self.session)
        prov = await settings_svc.get_active_provider()
        model = prov.model_embed if prov else "qwen/qwen3-embedding-4b"
        dim = EmbeddingService.known_dimension(model)
        if dim is not None:
            return dim
        # Иначе — попробовать через тестовый эмбеддинг
        if prov and prov.enabled and prov.get_api_key():
            svc = EmbeddingService(
                api_key=prov.get_api_key(),
                model=model,
                batch_size=1,
                base_url=prov.base_url,
            )
            vec = await svc.embed_one("тест", use_cache=False)
            return len(vec)
        return 2560  # безопасный fallback для qwen3-4b


__all__ = ["CollectionService"]
