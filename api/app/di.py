"""Service factory — единая точка создания сервисов с зависимостями."""
from __future__ import annotations

from functools import lru_cache

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.security import decrypt_secret
from app.deps import DBSession
from app.models.api_provider import ApiProvider
from app.services.cleaning_runner import CleaningRunner
from app.services.collection_service import CollectionService
from app.services.embedding_service import EmbeddingService
from app.services.feedback_service import FeedbackService
from app.services.folder_service import FolderService
from app.services.hierarchy_service import HierarchyService
from app.services.import_service import ImportService
from app.services.job_service import JobService
from app.services.material_service import MaterialService
from app.services.rerank_service import RerankService
from app.services.search_service import SearchService
from app.services.settings_service import SettingsService


async def _get_active_provider(session: AsyncSession) -> ApiProvider | None:
    svc = SettingsService(session)
    return await svc.get_active_provider() or await svc.get_provider("openrouter")


async def get_embedding_service(session: DBSession) -> EmbeddingService:
    prov = await _get_active_provider(session)
    settings = get_settings()
    if prov and prov.enabled and prov.api_key_encrypted:
        api_key = decrypt_secret(prov.api_key_encrypted)
        return EmbeddingService(
            api_key=api_key,
            model=prov.model_embed,
            batch_size=prov.batch_size,
            max_workers=prov.max_workers,
            base_url=prov.base_url,
        )
    # Fallback на env-ключ (если есть)
    return EmbeddingService(
        api_key=settings.openrouter_api_key or "missing",
        model=settings.openrouter_model_embed,
        batch_size=settings.openrouter_batch_size,
        max_workers=settings.openrouter_max_workers,
        base_url=settings.openrouter_base_url,
    )


async def get_rerank_service(session: DBSession) -> RerankService:
    prov = await _get_active_provider(session)
    settings = get_settings()
    if prov and prov.enabled and prov.api_key_encrypted:
        api_key = decrypt_secret(prov.api_key_encrypted)
        return RerankService(
            api_key=api_key,
            model=prov.model_rerank,
            base_url=prov.base_url,
        )
    return RerankService(
        api_key=settings.openrouter_api_key or "missing",
        model=settings.openrouter_model_rerank,
        base_url=settings.openrouter_base_url,
    )


def get_collection_service(session: DBSession) -> CollectionService:
    return CollectionService(session)


def get_material_service(
    session: DBSession,
    embedding: EmbeddingService = Depends(get_embedding_service),
) -> MaterialService:
    return MaterialService(session, embedding_service=embedding)


def get_folder_service(
    session: DBSession,
    embedding: EmbeddingService = Depends(get_embedding_service),
) -> FolderService:
    return FolderService(session, embedding_service=embedding)


def get_cleaning_runner(session: DBSession) -> CleaningRunner:
    return CleaningRunner(session)


def get_import_service(
    session: DBSession,
    embedding: EmbeddingService = Depends(get_embedding_service),
    cleaning: CleaningRunner = Depends(get_cleaning_runner),
) -> ImportService:
    return ImportService(session, embedding_service=embedding, cleaning=cleaning)


def get_search_service(
    session: DBSession,
    embedding: EmbeddingService = Depends(get_embedding_service),
    rerank: RerankService = Depends(get_rerank_service),
) -> SearchService:
    return SearchService(session, embedding_service=embedding, rerank_service=rerank)


def get_hierarchy_service(
    session: DBSession,
    embedding: EmbeddingService = Depends(get_embedding_service),
    rerank: RerankService = Depends(get_rerank_service),
) -> HierarchyService:
    return HierarchyService(session, embedding_service=embedding, rerank_service=rerank)


def get_feedback_service(session: DBSession) -> FeedbackService:
    return FeedbackService(session)


def get_job_service(session: DBSession) -> JobService:
    return JobService(session)


def get_settings_service(session: DBSession) -> SettingsService:
    return SettingsService(session)


__all__ = [
    "get_embedding_service",
    "get_rerank_service",
    "get_collection_service",
    "get_material_service",
    "get_folder_service",
    "get_cleaning_runner",
    "get_import_service",
    "get_search_service",
    "get_hierarchy_service",
    "get_feedback_service",
    "get_job_service",
    "get_settings_service",
]
